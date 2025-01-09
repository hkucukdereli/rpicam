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

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)
        logging.info(f"Created directory: {path}")

class VideoOutput(FileOutput):
    def __init__(self, filepath):
        super().__init__(filepath)
        self.filepath = filepath
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
            logging.error(f"Error writing frame: {e}")

    def close(self):
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
            mp4_file = h264_file.replace('.h264', '.mp4')
            
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
                mp4_file
            ]
            
            result = subprocess.run(convert_command, 
                                 capture_output=True,
                                 text=True)
            
            if result.returncode == 0:
                if os.path.exists(mp4_file) and os.path.getsize(mp4_file) > 0:
                    logging.info(f"Successfully converted to {mp4_file}")
                    os.remove(h264_file)  # Remove h264 file after successful conversion
                else:
                    logging.error("Conversion produced empty MP4 file")
            else:
                logging.error(f"FFmpeg conversion failed: {result.stderr}")
                    
        except Exception as e:
            logging.error(f"Error during conversion: {e}")
class SessionMetadata:
    def __init__(self, subject_path, start_time):
        self.filepath = os.path.join(
            subject_path,
            f"{config['subject_name']}_{start_time.strftime('%Y%m%d')}_{config['pi_identifier']}_metadata.yaml"
        )
        self.metadata = {
            'recording': {
                'subject_name': config['subject_name'],
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
                'frame_duration_limits': config['camera']['frame_duration_limits']
            }
        }
        self.save()
    
    def update_chunk(self, mp4_file, frame_count):
        """Update metadata with new chunk information"""
        self.metadata['recording']['video_files'].append(mp4_file)
        self.metadata['recording']['total_frames'] += frame_count
        self.save()
    
    def finalize(self, end_time):
        """Update end time when recording is finished"""
        self.metadata['recording']['end_time'] = end_time.isoformat()
        self.save()
    
    def save(self):
        """Save metadata to YAML file"""
        with open(self.filepath, 'w') as f:
            yaml.dump(self.metadata, f, default_flow_style=False)

    def outputframe(self, frame, keyframe=True, timestamp=None, packet=None, audio=None):
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
            logging.error(f"Error writing frame: {e}")

    def close(self):
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
            mp4_file = h264_file.replace('.h264', '.mp4')
            
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
                mp4_file
            ]
            
            result = subprocess.run(convert_command, 
                                 capture_output=True,
                                 text=True)
            
            if result.returncode == 0:
                if os.path.exists(mp4_file) and os.path.getsize(mp4_file) > 0:
                    logging.info(f"Successfully converted to {mp4_file}")
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
            
            # Get frame count from current output before switching
            old_output = self.encoder.output
            old_frame_count = old_output.frame_count if old_output else 0
            
            # Switch to new output
            self.encoder.output = new_output
            
            # Close old output and update metadata
            if old_output:
                old_output.close()
                mp4_file = old_output.filepath.replace('.h264', '.mp4')
                if os.path.exists(mp4_file):
                    self.metadata.update_chunk(mp4_file, old_frame_count)
            
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
            mp4_file = final_output.filepath.replace('.h264', '.mp4')
            if os.path.exists(mp4_file):
                self.metadata.update_chunk(mp4_file, final_output.frame_count)
        self.metadata.finalize(datetime.now())

def handle_shutdown(camera, recorder):
    print("\nInitiating safe shutdown...")
    try:
        if recorder:
            recorder.stop()
        
        if camera:
            camera.stop_recording()
            logging.info("Camera recording stopped")
        
        sleep(2)
        logging.shutdown()
        print("Shutdown complete. All files have been saved.")
    except Exception as e:
        logging.exception("Error during shutdown")
        print(f"Error during shutdown: {str(e)}")
    finally:
        sys.exit(0)

def main():
    try:
        # Setup directories
        subject_path = os.path.join(config['paths']['video_save_path'], config['subject_name'])
        ensure_directory_exists(subject_path)
        
        date = datetime.now().strftime('%Y%m%d')
        
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
        camera = Picamera2()
        
        # Create video configuration with YUV420 format
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

        # Add optional controls if they exist in config
        if 'sharpness' in config['camera']:
            controls_dict["Sharpness"] = config['camera']['sharpness']
        if 'noise_reduction' in config['camera']:
            controls_dict["NoiseReductionMode"] = config['camera']['noise_reduction']
        if 'analog_gain' in config['camera']:
            controls_dict["AnalogueGain"] = config['camera']['analog_gain']
        if 'exposure_value' in config['camera']:
            controls_dict["ExposureValue"] = config['camera']['exposure_value']
            
        camera.set_controls(controls_dict)

        # Setup initial recording
        first_file = os.path.join(
            subject_path,
            f"{config['subject_name']}_{date}_{config['pi_identifier']}_chunk001.h264"  # Use h264 extension
        )
        
        output = VideoOutput(first_file)
        encoder = H264Encoder()
        
        # Configure encoder for YUV420
        encoder.output = output
        encoder.repeat_sequence_header = True
        encoder.inline_headers = True
        encoder.bitrate = config['camera']['bitrate']
        
        # Start recording with specific configuration
        camera.start_recording(encoder=encoder, output=output)
        recorder = ContinuousRecording(camera, encoder, subject_path)
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