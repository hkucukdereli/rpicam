import threading
from time import sleep
import os
import logging
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
        session_folder = os.path.basename(self.video_path)
        return os.path.join(
            self.video_path,
            f"{session_folder}_{self.config['pi_identifier']}_chunk{self.chunk_counter:03d}.h264"
        )

    def _update_metadata(self, output):
        """Update metadata with chunk information"""
        if output and hasattr(output, 'mp4_filepath') and os.path.exists(output.mp4_filepath):
            self.total_frames += output.frame_count
            self.metadata.update_chunk(output.mp4_filepath, self.total_frames)
            logging.info(f"Updated metadata with {output.mp4_filepath}, total frames: {self.total_frames}")

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
            new_output = VideoOutput(new_file, self.config)
            
            old_output = self.encoder.output
            
            # Switch to new output
            self.encoder.output = new_output
            
            # Close old output and update metadata
            if old_output:
                old_output.close()
                self._update_metadata(old_output)
            
            self.chunk_counter += 1
            logging.info(f"Started new chunk: {new_file}")
        except Exception as e:
            logging.error(f"Error during split recording: {str(e)}")

    def stop(self):
        """Safely stop recording and ensure final metadata update"""
        self.recording = False
        try:
            if self.encoder and self.encoder.output:
                final_output = self.encoder.output
                final_output.close()  # This will trigger the MP4 conversion
                self._update_metadata(final_output)  # Update metadata with final chunk
            
            # Finalize metadata with end time
            self.metadata.finalize(datetime.now())
            logging.info(f"Recording stopped. Total frames recorded: {self.total_frames}")
        except Exception as e:
            logging.error(f"Error during recording stop: {e}")
