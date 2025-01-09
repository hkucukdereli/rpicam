import os
import csv
import threading
import logging
import time
from datetime import datetime
import subprocess
from picamera2.outputs import FileOutput

class VideoOutput(FileOutput):
    def __init__(self, filepath, config):
        super().__init__(filepath)
        self.filepath = filepath
        self.file = open(filepath, 'wb')
        self._is_closed = False
        self._lock = threading.Lock()
        self.config = config
        self.mp4_filepath = None
        
        timestamp_path = filepath.replace('.h264', '_timestamps.csv')
        self.timestamp_file = open(timestamp_path, 'w', newline='')
        self.timestamp_writer = csv.writer(self.timestamp_file)
        self.timestamp_writer.writerow(['frame_number', 'time_since_start', 'system_time'])
        
        self.frame_count = 0
        self.start_time = time.time()
        self.buffer_size = 0

    def outputframe(self, frame, keyframe=True, timestamp=None, packet=None, audio=None):
        with self._lock:
            if self._is_closed:
                return
            
            try:
                # Write video frame
                self.file.write(frame)
                self.buffer_size += len(frame)
                
                if self.buffer_size >= 512 * 1024:
                    self.file.flush()
                    self.buffer_size = 0
                
                # Write timestamp
                current_time = time.time()  # Get current time
                self.timestamp_writer.writerow([
                    self.frame_count,
                    f"{current_time - self.start_time:.6f}",
                    datetime.now().isoformat()
                ])
                self.frame_count += 1
                
                if self.frame_count % 10 == 0:
                    self.timestamp_file.flush()
                    
            except Exception as e:
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
                    
                self._convert_to_mp4()
            except Exception as e:
                logging.error(f"Error closing output: {e}")
                self.mp4_filepath = None
            
    def _convert_to_mp4(self):
        try:
            h264_file = self.filepath
            if not os.path.exists(h264_file):
                logging.error(f"H264 file not found: {h264_file}")
                return

            mp4_file = h264_file.replace('.h264', '.mp4')
            
            # Wait a moment to ensure file is completely written
            time.sleep(0.5)
            
            convert_command = [
                'ffmpeg', '-y',
                '-f', 'h264',
                '-r', str(int(1000000 / self.config['camera']['frame_duration_limits'][0])),
                '-i', h264_file,
                '-c:v', 'copy',
                '-movflags', '+faststart',
                mp4_file
            ]
            
            logging.info(f"Starting conversion of {h264_file} to {mp4_file}")
            result = subprocess.run(convert_command, 
                                 capture_output=True, 
                                 text=True)
            
            if result.returncode == 0:
                if os.path.exists(mp4_file) and os.path.getsize(mp4_file) > 0:
                    logging.info(f"Successfully converted to {mp4_file}")
                    self.mp4_filepath = mp4_file
                    os.remove(h264_file)
                else:
                    logging.error("Conversion produced empty MP4 file")
                    self.mp4_filepath = None
            else:
                logging.error(f"FFmpeg conversion failed: {result.stderr}")
                self.mp4_filepath = None
                    
        except Exception as e:
            logging.error(f"Error during conversion: {e}")
            self.mp4_filepath = None
