import os
import threading
from time import sleep, time
from datetime import datetime
import logging
import signal
import sys
from pathlib import Path
import subprocess
import yaml
import csv
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import FileOutput
from libcamera import controls, Transform

def load_config(config_path='camera_config.yaml'):
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

config = load_config()

def get_next_session_id(base_path, subject_name, recording_date):
    """
    Scan the base directory for existing session folders and return the next available session ID.
    Format: subject_YYYYMMDD_XX
    Example: If subject_20250109_1 exists, return "2"
    """
    try:
        # Create the prefix pattern to match
        folder_prefix = f"{subject_name}_{recording_date}"
        
        # Get all directories that match the pattern subject_YYYYMMDD_X
        existing_sessions = []
        if os.path.exists(base_path):
            for dirname in os.listdir(base_path):
                # Check if directory matches our pattern
                if dirname.startswith(folder_prefix):
                    try:
                        # Extract session ID from the end
                        session_id = int(dirname.split('_')[-1])
                        existing_sessions.append(session_id)
                    except (ValueError, IndexError):
                        continue
        
        # If no existing sessions, start with 1
        if not existing_sessions:
            return 1
        
        # Otherwise, return next available ID
        return max(existing_sessions) + 1
    except Exception as e:
        logging.error(f"Error getting next session ID: {e}")
        return 1

def get_session_folder_name(subject_name, recording_date, session_id):
    """Generate folder name in format subject_YYYYMMDD_X"""
    return f"{subject_name}_{recording_date}_{session_id}"

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)
        logging.info(f"Created directory: {path}")

class SessionMetadata:
    def __init__(self, subject_path, start_time):
        self.filepath = os.path.join(
            subject_path,
            f"{os.path.basename(subject_path)}_{config['pi_identifier']}_metadata.yaml"
        )
        
        # Calculate frame duration from framerate
        if 'framerate' in config['camera']:
            frame_duration = int(1000000 / config['camera']['framerate'])  # Convert fps to microseconds
        else:
            frame_duration = 100000  # Default 10 fps
            
        self.metadata = {
            'recording': {
                'subject_name': config['subject_name'],
                'recording_date': start_time.strftime('%Y%m%d'),
                'session_id': os.path.basename(subject_path).split('_')[2],  # Get session_id from folder name
                'pi_identifier': config['pi_identifier'],
                'start_time': start_time.isoformat(),
                'end_time': None,
                'total_frames': 0,
                'video_files': []
            },
            'camera': {
                'resolution': {
                    'width': config['camera']['resolution']['width'],
                    'height': config['camera']['resolution']['height']
                },
                'frame_format': config['camera']['frame_format'],
                'framerate': config['camera'].get('framerate', 10),  # Default to 10 fps if not specified
                'frame_duration': frame_duration
            }
        }
        self.save()

    def update_chunk(self, mp4_file, frame_count):
        """Update metadata with new chunk information"""
        if mp4_file not in self.metadata['recording']['video_files']:
            self.metadata['recording']['video_files'].append(mp4_file)
            self.metadata['recording']['total_frames'] += frame_count
            self.save()

    def finalize(self, end_time):
        """Update end time when recording is finished"""
        self.metadata['recording']['end_time'] = end_time.isoformat()
        self.save()

    def save(self):
        """Save metadata to YAML file"""
        try:
            with open(self.filepath, 'w') as f:
                yaml.dump(self.metadata, f, default_flow_style=False)
        except Exception as e:
            logging.error(f"Error saving metadata: {e}")

class VideoOutput(FileOutput):
    def __init__(self, filepath):
        super().__init__(filepath)
        self.filepath = filepath
        self.file = open(filepath, 'wb')
        self._is_closed = False
        self._lock = threading.Lock()
        
        # Create timestamp file using the same base filename pattern
        self.timestamp_path = filepath.replace('.h264', '_timestamps.csv')
        self.timestamp_file = open(self.timestamp_path, 'w', newline='')
        self.timestamp_writer = csv.writer(self.timestamp_file)
        self.timestamp_writer.writerow(['frame_number', 'time_since_start', 'system_time'])
        
        self.frame_count = 0
        self.start_time = time()
        self.buffer_size = 0
        self.mp4_filepath = None  # Will store the MP4 filepath after conversion

    def outputframe(self, frame, keyframe=True, timestamp=None, packet=None, audio=None):
        with self._lock:
            if self._is_closed:
                return
            
            try:
                # Write video frame
                self.file.write(frame)
                self.buffer_size += len(frame)
                
                # Force flush more frequently
                if self.buffer_size >= 512 * 1024:  # Flush every 512KB
                    self.file.flush()
                    self.buffer_size = 0
                
                # Write timestamp
                self.timestamp_writer.writerow([
                    self.frame_count,
                    f"{time() - self.start_time:.6f}",
                    datetime.now().isoformat()
                ])
                self.frame_count += 1
                
                # Flush timestamp file more frequently
                if self.frame_count % 10 == 0:  # Every 10 frames
                    self.timestamp_file.flush()
                    
            except Exception as e:
                # Only log if we're not in the process of closing
                if not self._is_closed:
                    logging.error(f"Error writing frame: {e}")

    def close(self):
        with self._lock:
            if self._is_closed:
                return
            
            self._is_closed = True
            
            try:
                if hasattr(self, 'file'):
                    self.file.flush()
                    self.file.close()
                if hasattr(self, 'timestamp_file'):
                    self.timestamp_file.flush()
                    self.timestamp_file.close()
                    
                # Convert h264 to mp4 after closing
                self._convert_to_mp4()
            except Exception as e:
                logging.error(f"Error closing output: {e}")

    def _convert_to_mp4(self):
        try:
            h264_file = self.filepath
            self.mp4_filepath = h264_file.replace('.h264', '.mp4')
            
            # Calculate framerate from frame_duration_limits
            frame_duration = config['camera']['frame_duration_limits'][0]  # in microseconds
            framerate = int(1000000 / frame_duration)  # convert to fps
            
            # FFmpeg command with explicit framerate
            convert_command = [
                'ffmpeg', '-y',
                '-f', 'h264',
                '-r', str(framerate),
                '-i', h264_file,
                '-c:v', 'copy',
                '-movflags', '+faststart',
                self.mp4_filepath
            ]
            
            result = subprocess.run(convert_command, 
                                 capture_output=True,
                                 text=True)
            
            if result.returncode == 0:
                if os.path.exists(self.mp4_filepath) and os.path.getsize(self.mp4_filepath) > 0:
                    logging.info(f"Successfully converted to {self.mp4_filepath}")
                    os.remove(h264_file)  # Remove h264 file after successful conversion
                else:
                    logging.error("Conversion produced empty MP4 file")
            else:
                logging.error(f"FFmpeg conversion failed: {result.stderr}")
                    
        except Exception as e:
            logging.error(f"Error during conversion: {e}")

class ContinuousRecording:
    def __init__(self, camera, encoder, video_path, start_time):
        self.camera = camera
        self.encoder = encoder
        self.video_path = video_path
        self.chunk_length = config['recording']['chunk_length']
        self.recording = True
        self.chunk_counter = 1
        self.metadata = SessionMetadata(video_path, start_time)
        self.session_folder = os.path.basename(video_path)
        
    def _generate_filename(self):
        """Generate consistent filename for chunks"""
        return os.path.join(
            self.video_path,
            f"{self.session_folder}_{config['pi_identifier']}_chunk{self.chunk_counter:03d}.h264"
        )

    def start(self):
        threading.Thread(target=self._monitor, daemon=True).start()

    def _monitor(self):
        while self.recording:
            sleep(self.chunk_length)
            if self.recording:
                self._split_recording()

    def _split_recording(self):
        try:
            new_file = self._generate_filename()
            new_output = VideoOutput(new_file)
            
            # Get frame count from current output before switching
            old_output = self.encoder.output
            old_frame_count = old_output.frame_count if old_output else 0
            
            # Switch to new output
            self.encoder.output = new_output
            
            # Close old output and update metadata
            if old_output:
                old_output.close()
                # Use the stored mp4 filepath that was set during conversion
                if hasattr(old_output, 'mp4_filepath') and os.path.exists(old_output.mp4_filepath):
                    self.metadata.update_chunk(old_output.mp4_filepath, old_frame_count)
            
            self.chunk_counter += 1
            logging.info(f"Started new chunk: {new_file}")
        except Exception as e:
            logging.error(f"Error during split recording: {str(e)}")

    def stop(self):
        self.recording = False
        # Update metadata with final chunk and end time
        if self.encoder and self.encoder.output:
            final_output = self.encoder.output
            final_output.close()
            # Use the stored mp4 filepath that was set during conversion
            if hasattr(final_output, 'mp4_filepath') and os.path.exists(final_output.mp4_filepath):
                self.metadata.update_chunk(final_output.mp4_filepath, final_output.frame_count)
        self.metadata.finalize(datetime.now())

def handle_shutdown(camera, recorder):
    print("\nInitiating safe shutdown...")
    try:
        # First stop recording to prevent new frames
        if camera:
            camera.stop_recording()
            logging.info("Camera recording stopped")
        
        # Then stop the recorder and handle metadata
        if recorder:
            recorder.stop()
            logging.info("Recorder stopped")
        
        # Give time for final operations
        sleep(1)
        logging.shutdown()
        print("Shutdown complete. All files have been saved.")
    except Exception as e:
        logging.exception("Error during shutdown")
        print(f"Error during shutdown: {str(e)}")
    finally:
        sys.exit(0)

def main():
    try:
        # Get current date in YYYYMMDD format
        recording_date = datetime.now().strftime('%Y%m%d')
        
        # Get next available session ID
        base_video_path = config['paths']['video_save_path']
        subject_name = config['subject_name']
        session_id = get_next_session_id(base_video_path, subject_name, recording_date)
        
        # Create session-specific directory with new naming format
        session_folder = get_session_folder_name(subject_name, recording_date, session_id)
        subject_path = os.path.join(base_video_path, session_folder)
        ensure_directory_exists(subject_path)
        
        # Setup logging
        log_file = os.path.join(
            subject_path,
            f"{session_folder}_{config['pi_identifier']}.log"
        )
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s:%(levelname)s:%(message)s'
        )
        
        logging.info(f"Starting recording session {session_id}")

        # Initialize camera
        camera = Picamera2()
        
        # Create video configuration
        video_config = camera.create_video_configuration(
            main={
                "size": (
                    config['camera']['resolution']['width'],
                    config['camera']['resolution']['height']
                ),
                "format": "YUV420"
            },
            encode="main"
        )
        
        camera.configure(video_config)
        
        # Set camera controls with correct ranges and cases
        controls_dict = {
            # Auto-focus settings
            "AfMode": controls.AfModeEnum.Manual,
            "LensPosition": config['camera']['lens']['position'],
            
            # Frame rate control
            "FrameDurationLimits": tuple(config['camera']['frame_duration_limits']),
            
            # Image quality controls
            "Brightness": config['camera']['brightness'],
            "Contrast": config['camera']['contrast'],
            "Saturation": 0.0,  # Direct value for grayscale
            
            # Disable auto white balance since we're doing grayscale
            "AwbEnable": False
        }
        
        camera.set_controls(controls_dict)

        # Get start time for the session
        start_time = datetime.now()
        
        # Create encoder
        encoder = H264Encoder()
        encoder.repeat_sequence_header = True
        encoder.inline_headers = True
        encoder.bitrate = config['camera']['bitrate']
        
        # Create recorder instance first
        recorder = ContinuousRecording(camera, encoder, subject_path, start_time)
        
        # Setup initial recording using recorder's filename generation
        first_file = recorder._generate_filename()
        output = VideoOutput(first_file)
        encoder.output = output
        
        # Start recording
        camera.start_recording(encoder=encoder, output=output)
        recorder.start()

        def signal_handler(signum, frame):
            handle_shutdown(camera, recorder)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print("\nRecording started. Press Ctrl+C to safely stop the recording...")

        while True:
            sleep(1)

    except Exception as e:
        logging.exception("Error during recording")
        print(f"\nError: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
    