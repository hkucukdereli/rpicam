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
from libcamera import controls

# Load configuration
def load_config(config_path='camera_config.yaml'):
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

config = load_config()

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)
        logging.info(f"Created directory: {path}")

def setup_directories():
    subject_path = os.path.join(config['paths']['video_save_path'], config['subject_name'])
    ensure_directory_exists(subject_path)
    
    date = datetime.now().strftime('%Y%m%d')
    metadata_filename = f"{config['subject_name']}_{date}_{config['pi_identifier']}_metadata.yaml"
    metadata_path = os.path.join(subject_path, metadata_filename)
    
    if os.path.exists(metadata_path):
        raise FileExistsError(f"Metadata file already exists for today: {metadata_path}")
        
    return subject_path, metadata_path

def initialize_metadata(camera, start_time, metadata_path):
    metadata = {
        'recording': {
            'subject_name': config['subject_name'],
            'start_time': start_time.isoformat(),
            'pi_identifier': config['pi_identifier'],
            'frame_rate': 1 / (config['camera']['frame_duration_limits'][0] / 1000000),
        },
        'camera': {
            'resolution': {
                'width': config['camera']['resolution']['width'],
                'height': config['camera']['resolution']['height']
            },
            'format': config['camera']['frame_format'],
            'lens_position': config['camera']['lens']['position'],
            'frame_duration_limits': config['camera']['frame_duration_limits']
        }
    }
    
    with open(metadata_path, 'w') as f:
        yaml.dump(metadata, f, default_flow_style=False)

class EnhancedFileOutput(FileOutput):
    def __init__(self, filepath, width, height):
        self.filepath = filepath
        self.file = open(filepath, 'wb')
        self.timestamp_file = open(filepath.replace('.h264', '_timestamps.csv'), 'w', newline='')
        self.timestamp_writer = csv.writer(self.timestamp_file)
        self.timestamp_writer.writerow(['frame_number', 'time_since_start', 'system_time'])
        self.frame_count = 0
        self.start_time = time()
        self.width = width
        self.height = height

    def outputframe(self, frame, keyframe=True, timestamp=None, packet=None, audio=None):
        self.file.write(frame)
        self.file.flush()  # Ensure frame is written immediately
        
        self.timestamp_writer.writerow([
            self.frame_count,
            f"{time() - self.start_time:.6f}",
            datetime.now().isoformat()
        ])
        self.timestamp_file.flush()  # Ensure timestamp is written immediately
        self.frame_count += 1

    def close(self):
        if hasattr(self, 'file') and self.file:
            self.file.close()
        if hasattr(self, 'timestamp_file') and self.timestamp_file:
            self.timestamp_file.close()
        
        # Convert to MP4 after closing
        self._convert_to_mp4()

    def _convert_to_mp4(self):
        try:
            h264_file = self.filepath
            mp4_file = h264_file.replace('.h264', '.mp4')
            
            # Ensure the h264 file exists and has content
            if not os.path.exists(h264_file) or os.path.getsize(h264_file) == 0:
                logging.error(f"H264 file is missing or empty: {h264_file}")
                return
            
            # Construct ffmpeg command with explicit format and size
            convert_command = (
                f"ffmpeg -y "
                f"-f h264 "
                f"-video_size {self.width}x{self.height} "
                f"-framerate 30 "
                f"-i {h264_file} "
                f"-c:v copy "
                f"-movflags faststart "
                f"{mp4_file}"
            )
            
            # Execute conversion
            result = subprocess.run(
                convert_command,
                shell=True,
                capture_output=True,
                text=True
            )
            
            # Check conversion result
            if result.returncode == 0 and os.path.exists(mp4_file) and os.path.getsize(mp4_file) > 0:
                logging.info(f"Successfully converted {h264_file} to {mp4_file}")
                os.remove(h264_file)  # Remove h264 file after successful conversion
            else:
                logging.error(f"Conversion failed: {result.stderr}")
                if os.path.exists(mp4_file):
                    os.remove(mp4_file)
                
        except Exception as e:
            logging.error(f"Error during conversion: {str(e)}")

class VideoOutput(FileOutput):
    def __init__(self, filepath):
        super().__init__(filepath)
        self.filepath = filepath
        # Open the file in binary write mode
        self.file = open(filepath, 'wb')
        
        # Create timestamp file
        timestamp_path = filepath.replace('.h264', '_timestamps.csv')
        self.timestamp_file = open(timestamp_path, 'w', newline='')
        self.timestamp_writer = csv.writer(self.timestamp_file)
        self.timestamp_writer.writerow(['frame_number', 'time_since_start', 'system_time'])
        
        self.frame_count = 0
        self.start_time = time()
        self.buffer_size = 0

    def outputframe(self, frame, keyframe=True, timestamp=None, packet=None, audio=None):
        try:
            # Write video frame
            self.file.write(frame)
            self.buffer_size += len(frame)
            
            # Force flush every 1MB
            if self.buffer_size >= 1024 * 1024:
                self.file.flush()
                self.buffer_size = 0
            
            # Write timestamp
            self.timestamp_writer.writerow([
                self.frame_count,
                f"{time() - self.start_time:.6f}",
                datetime.now().isoformat()
            ])
            self.frame_count += 1
            
            # Flush timestamp file periodically
            if self.frame_count % 30 == 0:  # Every 30 frames
                self.timestamp_file.flush()
                
        except Exception as e:
            logging.error(f"Error writing frame: {e}")

    def close(self):
        try:
            if hasattr(self, 'file'):
                self.file.flush()
                self.file.close()
            if hasattr(self, 'timestamp_file'):
                self.timestamp_file.flush()
                self.timestamp_file.close()
                
            # Only attempt conversion if we have frames
            if self.frame_count > 0:
                self._convert_to_mp4()
        except Exception as e:
            logging.error(f"Error closing output: {e}")

    def _convert_to_mp4(self):
        try:
            h264_file = self.filepath
            mp4_file = h264_file.replace('.h264', '.mp4')
            
            # Ensure source file exists and has content
            if not os.path.exists(h264_file) or os.path.getsize(h264_file) == 0:
                logging.error(f"H264 file is missing or empty: {h264_file}")
                return

            # Calculate framerate from frame_duration_limits
            frame_duration = config['camera']['frame_duration_limits'][0]  # in microseconds
            framerate = 1000000 / frame_duration  # convert to fps
            
            # FFmpeg command with explicit framerate
            convert_command = (
                f"ffmpeg -y "
                f"-f h264 "
                f"-r {framerate} "  # Set input framerate
                f"-i {h264_file} "
                f"-c:v copy "
                f"-metadata:s:v:0 \"framerate={framerate}\" "  # Add framerate metadata
                f"{mp4_file}"
            )
            
            logging.info(f"Converting {h264_file} to {mp4_file}")
            result = subprocess.run(
                convert_command,
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                if os.path.exists(mp4_file) and os.path.getsize(mp4_file) > 0:
                    logging.info(f"Successfully converted to {mp4_file}")
                    os.remove(h264_file)
                else:
                    logging.error("Conversion produced empty MP4 file")
            else:
                logging.error(f"FFmpeg conversion failed: {result.stderr}")
                if os.path.exists(mp4_file):
                    os.remove(mp4_file)
                    
        except Exception as e:
            logging.error(f"Error during conversion: {e}")

class ContinuousRecording:
    def __init__(self, camera, encoder, video_path):
        self.camera = camera
        self.encoder = encoder
        self.video_path = video_path
        self.chunk_length = config['recording']['chunk_length']
        self.recording = True
        self.chunk_counter = 1
        
    def _generate_filename(self):
        date = datetime.now().strftime('%Y%m%d')
        return os.path.join(
            self.video_path,
            f"{config['subject_name']}_{date}_{config['pi_identifier']}_chunk{self.chunk_counter:03d}.h264"
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
            
            # Switch output file
            old_output = self.encoder.output
            self.encoder.output = new_output
            
            # Close old output (this will trigger MP4 conversion)
            if old_output:
                old_output.close()
            
            self.chunk_counter += 1
            logging.info(f"Started new chunk: {new_file}")
        except Exception as e:
            logging.error(f"Error during split recording: {str(e)}")

    def stop(self):
        self.recording = False

def handle_shutdown(camera, recorder):
    print("\nInitiating safe shutdown... Please wait for conversions to complete.")
    try:
        if recorder:
            recorder.stop()
        
        if camera:
            camera.stop_recording()
            logging.info("Camera recording stopped")
            
        # Give time for final conversion
        sleep(5)
        
        logging.shutdown()
        print("Shutdown complete. All files have been saved and converted.")
    except Exception as e:
        logging.exception("Error during shutdown")
        print(f"Error during shutdown: {str(e)}")
    finally:
        sys.exit(0)

def main():
    try:
        # Setup directories and check for existing metadata
        subject_path = os.path.join(config['paths']['video_save_path'], config['subject_name'])
        ensure_directory_exists(subject_path)
        
        date = datetime.now().strftime('%Y%m%d')
        metadata_filename = f"{config['subject_name']}_{date}_{config['pi_identifier']}_metadata.yaml"
        metadata_path = os.path.join(subject_path, metadata_filename)
        
        if os.path.exists(metadata_path):
            raise FileExistsError(f"Metadata file already exists for today: {metadata_path}")

        # Setup logging
        log_file = os.path.join(
            subject_path,
            f"{config['subject_name']}_{date}_{config['pi_identifier']}.log"
        )
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s:%(levelname)s:%(message)s'
        )
        
        logging.info("Starting recording session")

        # Initialize camera
        camera = Picamera2(0)
        video_config = camera.create_video_configuration(
            main={
                "size": (
                    config['camera']['resolution']['width'],
                    config['camera']['resolution']['height']
                ),
                "format": config['camera']['frame_format']
            },
            encode="main"
        )
        camera.configure(video_config)
        
        camera.set_controls({
            "AfMode": controls.AfModeEnum.Manual,
            "LensPosition": config['camera']['lens']['position'],
            "FrameDurationLimits": tuple(config['camera']['frame_duration_limits'])
        })

        # Initialize metadata
        start_datetime = datetime.now()
        initialize_metadata(camera, start_datetime, metadata_path)
        
        # Setup initial recording
        first_file = os.path.join(
            subject_path,
            f"{config['subject_name']}_{date}_{config['pi_identifier']}_chunk001.h264"
        )
        
        output = VideoOutput(first_file)
        encoder = H264Encoder()
        
        # Configure encoder
        encoder.output = output
        encoder.repeat_sequence_header = True
        encoder.inline_headers = True
        
        # Start recording
        camera.start_recording(encoder, output)
        recorder = ContinuousRecording(camera, encoder, subject_path)
        recorder.start()

        def signal_handler(signum, frame):
            handle_shutdown(camera, recorder)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print("\nRecording started. Press Ctrl+C to safely stop the recording...")
        while True:
            sleep(1)

    except FileExistsError as e:
        print(f"\nError: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logging.exception("Error during recording")
        print(f"\nError: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()