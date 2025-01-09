import os
import threading
import logging
import time
from datetime import datetime
from .video_output import VideoOutput
from .metadata import SessionMetadata

class ContinuousRecording:
    def __init__(self, camera, encoder, video_path, start_time, config, initial_chunk=1):
        self.camera = camera
        self.encoder = encoder
        self.video_path = video_path
        self.chunk_length = config['recording']['chunk_length']
        self.recording = True
        self.chunk_counter = initial_chunk + 1
        self.config = config
        self.metadata = SessionMetadata(video_path, start_time, config)
        self.total_frames = 0

    def _generate_filename(self):
        try:
            session_folder = os.path.basename(self.video_path)
            return os.path.join(
                self.video_path,
                f"{session_folder}_{self.config['pi_identifier']}_chunk{self.chunk_counter:03d}.h264"
            )
        except Exception as e:
            logging.error(f"Error generating filename: {e}")
            return None

    def _update_metadata(self, output):
        """Update metadata with chunk information"""
        try:
            if output is None:
                logging.warning("No output provided for metadata update")
                return
                
            if not hasattr(output, 'mp4_filepath'):
                logging.warning("Output has no mp4_filepath attribute")
                return
                
            if output.mp4_filepath is None:
                logging.warning("Output mp4_filepath is None")
                return
                
            if not os.path.exists(output.mp4_filepath):
                logging.warning(f"MP4 file does not exist: {output.mp4_filepath}")
                return
                
            self.total_frames += output.frame_count
            self.metadata.update_chunk(output.mp4_filepath, self.total_frames)
            logging.info(f"Updated metadata with {output.mp4_filepath}, total frames: {self.total_frames}")
            
        except Exception as e:
            logging.error(f"Error updating metadata: {e}")

    def start(self):
        threading.Thread(target=self._monitor, daemon=True).start()

    def _monitor(self):
        while self.recording:
            time.sleep(self.chunk_length)
            if self.recording:
                self._split_recording()

    def _split_recording(self):
        try:
            new_file = self._generate_filename()
            if not new_file:
                logging.error("Failed to generate new filename")
                return
                
            new_output = VideoOutput(new_file, self.config)
            old_output = self.encoder.output
            
            self.encoder.output = new_output
            
            if old_output:
                try:
                    old_output.close()
                    time.sleep(1)  # Using full module path
                    self._update_metadata(old_output)
                except Exception as e:
                    logging.error(f"Error handling old output: {e}")
            
            self.chunk_counter += 1
            logging.info(f"Started new chunk: {new_file}")
        except Exception as e:
            logging.error(f"Error during split recording: {str(e)}")

    def stop(self):
        self.recording = False
        try:
            if self.encoder and self.encoder.output:
                final_output = self.encoder.output
                final_output.close()
                time.sleep(1)  # Using full module path
                self._update_metadata(final_output)
            
            self.metadata.finalize(datetime.now())
            logging.info(f"Recording stopped. Total frames recorded: {self.total_frames}")
        except Exception as e:
            logging.error(f"Error during recording stop: {e}")
