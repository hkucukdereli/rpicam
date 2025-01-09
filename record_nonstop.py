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
        timestamp_path = filepath.replace('.mp4', '_timestamps.csv')
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
            if self.frame_count % 30 == 0:
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
        except Exception as e:
            logging.error(f"Error closing output: {e}")

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
            f"{config['subject_name']}_{date}_{config['pi_identifier']}_chunk{self.chunk_counter:03d}.mp4"
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
            
            old_output = self.encoder.output
            self.encoder.output = new_output
            
            if old_output:
                old_output.close()
            
            self.chunk_counter += 1
            logging.info(f"Started new chunk: {new_file}")
        except Exception as e:
            logging.error(f"Error during split recording: {str(e)}")

    def stop(self):
        self.recording = False

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

        # Initialize camera with grayscale settings
        camera = Picamera2()
        
        # Create video configuration with grayscale
        video_config = camera.create_video_configuration(
            main={
                "size": (
                    config['camera']['resolution']['width'],
                    config['camera']['resolution']['height']
                ),
                "format": "YUV420"  # Using YUV420 for grayscale
            },
            transform=Transform(colour_space="Rec709")  # This helps ensure proper grayscale conversion
        )
        
        camera.configure(video_config)
        
        # Set camera controls
        camera.set_controls({
            "AfMode": controls.AfModeEnum.Manual,
            "LensPosition": config['camera']['lens']['position'],
            "FrameDurationLimits": tuple(config['camera']['frame_duration_limits']),
            "Brightness": config['camera']['brightness'],
            "Contrast": config['camera']['contrast'],
            "ColourGains": (1.0, 1.0)  # Neutral color gains for grayscale
        })

        # Setup initial recording
        first_file = os.path.join(
            subject_path,
            f"{config['subject_name']}_{date}_{config['pi_identifier']}_chunk001.mp4"
        )
        
        output = VideoOutput(first_file)
        encoder = H264Encoder(bitrate=config['camera']['bitrate'])
        
        # Configure encoder for better compatibility
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

    except Exception as e:
        logging.exception("Error during recording")
        print(f"\nError: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()