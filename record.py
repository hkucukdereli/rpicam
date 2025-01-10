from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
import libcamera 
import time
import yaml
import signal
import sys
import os
from datetime import datetime
import threading
from queue import Queue

class VideoRecorder:
    def __init__(self, config_path='camera_config.yaml'):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Set up session information
        self.date_str = datetime.now().strftime("%Y%m%d")
        self.session_id = self._determine_session_id()
        self.chunk_counter = 0
        
        # Create session directory
        self.session_dir = self._create_session_directory()
        
        # Initialize camera
        self.picam2 = Picamera2()
        self.configure_camera()
        
        # Initialize recording state
        self.is_recording = False
        self.recording_start_time = None
        self.video_files = []
        self.frame_counts = {}
        self.frame_timestamps = []
        self.total_frames = 0

        # Frame counting variables
        self.current_chunk_frames = 0
        self.current_chunk_filename = None
            
        # Create queue for encoders
        self.encoder_queue = Queue(maxsize=2)
        
        # Set up signal handling
        signal.signal(signal.SIGINT, self.handle_shutdown)
    
    def _determine_session_id(self):
        """
        Determine session ID by checking existing directories for the current date
        Returns 1 if no existing sessions found, otherwise returns max + 1
        """
        base_path = self.config['paths']['video_save_path']
        subject_id = self.config['subject_name']
        
        # Pattern to match: subject_id_YYYYMMDD_XX
        prefix = f"{subject_id}_{self.date_str}_"
        
        max_session = 0
        
        # Check all directories in the base path
        if os.path.exists(base_path):
            for dirname in os.listdir(base_path):
                # Check if directory matches our naming pattern
                if dirname.startswith(prefix):
                    try:
                        # Extract session number from the end
                        session_str = dirname.split('_')[-1]
                        session_num = int(session_str)
                        max_session = max(max_session, session_num)
                    except (ValueError, IndexError):
                        # Skip directories that don't match the expected format
                        continue
        
        # Return next session number (1 if no existing sessions found)
        return max_session + 1
    
    def _create_session_directory(self):
        """Create and return the session directory path"""
        session_name = f"{self.config['subject_name']}_{self.date_str}_{self.session_id:02d}"
        session_dir = os.path.join(self.config['paths']['video_save_path'], session_name)
        
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
            print(f"Created new session directory: {session_dir}")
        
        return session_dir
    
    def _generate_filename(self, file_type):
        """Generate filename based on type (video, metadata, timestamps)"""
        base_name = f"{self.config['subject_name']}_{self.date_str}_{self.session_id:02d}"
        
        if file_type == 'video':
            return f"{base_name}_{self.chunk_counter:03d}.h264"
        elif file_type == 'metadata':
            return f"{base_name}_metadata.yaml"
        elif file_type == 'timestamps':
            return f"{base_name}_timestamps.txt"
        
        return None

    def configure_camera(self):
        # Calculate frame duration in microseconds from framerate
        frame_duration = int(1_000_000 / self.config['camera']['framerate'])

        # Create camera configuration
        cam_config = {
            'use_case': 'video',
            'transform': libcamera.Transform(0),
            'colour_space': libcamera.ColorSpace.Rec709(),
            'buffer_count': 6,
            'queue': True,
            'main': {
                'format': self.config['camera']['frame_format'],
                'size': (
                    self.config['camera']['resolution']['width'],
                    self.config['camera']['resolution']['height']
                ),
                'preserve_ar': True
            },
            'lores': None,  # Added this required key
            'controls': {
                'NoiseReductionMode': self.config['camera']['noise_reduction'],
                'FrameDurationLimits': (frame_duration, frame_duration)
            },
            'raw': {  # Adding raw configuration as seen in default config
                'format': 'SRGGB10_CSI2P',
                'size': (
                    self.config['camera']['resolution']['width'],
                    self.config['camera']['resolution']['height']
                )
            },
            'sensor': {}, 
            'display': None,
            'encode': 'main'
        }
        
        self.picam2.configure(cam_config)
        
        self.picam2.set_controls({
            "AfMode": libcamera.controls.AfModeEnum.Manual,
            "LensPosition": self.config['camera']['lens']['position'],
            "Brightness": self.config['camera']['brightness'],
            "Contrast": self.config['camera']['contrast'],
            "Saturation": self.config['camera']['saturation'],
            "Sharpness": self.config['camera']['sharpness'],
            "AnalogueGain": self.config['camera']['analog_gain'],
            "ExposureValue": self.config['camera']['exposure_value'],
            "NoiseReductionMode": self.config['camera']['noise_reduction'],
            "AwbEnable": False
            # "Brightness": max(min(self.config['camera']['brightness'], 1.0), -1.0),
            # "Contrast": max(min(self.config['camera']['contrast'], 32.0), 1.0),
            # "Saturation": max(min(self.config['camera']['saturation'], 32.0), 1.0),
            # "Sharpness": max(min(self.config['camera']['sharpness'], 16.0), 1.0),
            # "AnalogueGain": max(min(self.config['camera']['analog_gain'], 16.0), 1.0),
            # "ExposureValue": max(min(self.config['camera']['exposure_value'], 8.0), -8.0),
            # "NoiseReductionMode": min(self.config['camera']['noise_reduction'], 4),
        })

        # Set up frame callback
        self.picam2.pre_callback = self.frame_callback

    def frame_callback(self, request):
        """Callback that runs for each frame"""
        try:
            if self.is_recording and hasattr(self, 'current_chunk_frames'):
                current_time = time.time()
                elapsed_time = current_time - self.recording_start_time.timestamp()
                
                # Record frame data
                self.frame_timestamps.append({
                    'frame': self.total_frames,
                    'elapsed': elapsed_time,
                    'system_time': current_time
                })
                
                self.current_chunk_frames += 1
                self.total_frames += 1
        except Exception as e:
            print(f"Error in frame callback: {e}")

    def create_encoder_output(self):
        """Create new encoder and output for recording"""
        try:
            self.chunk_counter += 1
            video_filename = self._generate_filename('video')
            video_path = os.path.join(self.session_dir, video_filename)
            
            print(f"Creating encoder for: {video_path}")
            encoder = H264Encoder(bitrate=self.config['camera']['bitrate'])
            output = FileOutput(video_path)
            
            return encoder, output, video_filename
        except Exception as e:
            print(f"Error in create_encoder_output: {e}")
            raise

    def record_frames(self, video_filename):
        frame_count = 0
        chunk_start_time = time.time()
        
        while (time.time() - chunk_start_time < self.config['recording']['chunk_length'] 
            and self.is_recording):
            current_time = time.time()
            elapsed_time = current_time - self.recording_start_time.timestamp()
            
            # Record frame data as: frame_number, elapsed_time, system_time
            self.frame_timestamps.append({
                'frame': self.total_frames,
                'elapsed': elapsed_time,
                'system_time': current_time
            })
            
            frame_count += 1
            self.total_frames += 1
            time.sleep(1/self.config['camera']['framerate'])
                
        self.frame_counts[video_filename] = frame_count

    def start_recording(self):
        self.is_recording = True
        self.recording_start_time = datetime.now()
        self.total_frames = 0
        
        while self.is_recording:
            try:
                # Create new encoder and output
                encoder, output, video_filename = self.create_encoder_output()
                self.video_files.append(video_filename)
                
                # Reset chunk frame counter
                self.current_chunk_frames = 0
                
                # Start recording
                self.picam2.start_recording(encoder, output)
                print(f"Started recording chunk: {video_filename}")
                
                # Record for chunk duration
                chunk_start = time.monotonic()  # Use monotonic for better timing
                while (time.monotonic() - chunk_start < self.config['recording']['chunk_length'] 
                    and self.is_recording):
                    current_time = time.monotonic() - chunk_start
                    if int(current_time) % 10 == 0:
                        expected_frames = int(current_time * self.config['camera']['framerate'])
                        print(f"Time: {current_time:.1f}s, Current chunk frames: {self.current_chunk_frames}, Expected: {expected_frames}")
                    time.sleep(0.1)
                
                # Stop recording
                self.picam2.stop_recording()
                
                # Store the frame count for this chunk
                self.frame_counts[video_filename] = self.current_chunk_frames
                print(f"Completed chunk {video_filename} with {self.current_chunk_frames} frames "
                    f"(expected: {self.config['recording']['chunk_length'] * self.config['camera']['framerate']:.0f})")
                    
            except Exception as e:
                import traceback
                print(f"Error in recording loop: {str(e)}")
                print(traceback.format_exc())
                self.is_recording = False
                break

        # Final cleanup
        try:
            self.picam2.stop_recording()
        except Exception as e:
            print(f"Error during final cleanup: {e}")
            
    def write_metadata(self):
        metadata = {
            'subject_id': self.config['subject_name'],
            'pi_identifier': self.config['pi_identifier'],
            'session_id': self.session_id,
            'date': self.date_str,
            'start_time': self.recording_start_time.isoformat(),
            'end_time': datetime.now().isoformat(),
            'framerate': self.config['camera']['framerate'],
            'total_frames': self.total_frames,
            'resolution': {
                'width': self.config['camera']['resolution']['width'],
                'height': self.config['camera']['resolution']['height']
            },
            'chunks': [
                {
                    'filename': video_file,
                    'frame_count': self.frame_counts[video_file],
                    'chunk_id': idx + 1
                }
                for idx, video_file in enumerate(self.video_files)
            ]
        }
        
        # Write metadata to YAML file
        metadata_filename = self._generate_filename('metadata')
        metadata_path = os.path.join(self.session_dir, metadata_filename)
        
        with open(metadata_path, 'w') as f:
            yaml.dump(metadata, f, default_flow_style=False)
        
        # Write timestamps with all three values
        timestamp_filename = self._generate_filename('timestamps')
        timestamp_path = os.path.join(self.session_dir, timestamp_filename)
        
        with open(timestamp_path, 'w') as f:
            # Write header
            f.write("frame_number,elapsed_time_seconds,system_time\n")
            # Write data
            for ts in self.frame_timestamps:
                f.write(f"{ts['frame']},{ts['elapsed']:.6f},{ts['system_time']:.6f}\n")

    def handle_shutdown(self, signum, frame):
        print("\nGracefully shutting down...")
        self.is_recording = False
        
        try:
            self.picam2.stop_recording()
        except:
            pass  # Ignore any errors during stop_recording
        
        # Write metadata
        self.write_metadata()
        
        # Clean up
        self.picam2.close()
        sys.exit(0)

def main():
    recorder = VideoRecorder()
    try:
        print(f"Starting recording session {recorder.session_id:02d}")
        recorder.start_recording()
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received")
        recorder.handle_shutdown(None, None)
    except Exception as e:
        print(f"Error during recording: {e}")
        recorder.handle_shutdown(None, None)


if __name__ == "__main__":
    main()