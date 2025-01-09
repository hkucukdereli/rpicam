import threading
from time import sleep
import os
import logging
from datetime import datetime
from .video_output import VideoOutput
from .metadata import SessionMetadata

class ContinuousRecording:
    def __init__(self, camera, encoder, video_path, start_time, config):
        self.camera = camera
        self.encoder = encoder
        self.video_path = video_path
        self.chunk_length = config['recording']['chunk_length']
        self.recording = True
        self.chunk_counter = 1
        self.config = config
        self.metadata = SessionMetadata(video_path, start_time, config)
        
    def _generate_filename(self):
        session_folder = os.path.basename(self.video_path)
        return os.path.join(
            self.video_path,
            f"{session_folder}_{self.config['pi_identifier']}_chunk{self.chunk_counter:03d}.h264"
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
            new_output = VideoOutput(new_file, self.config)
            
            old_output = self.encoder.output
            old_frame_count = old_output.frame_count if old_output else 0
            
            self.encoder.output = new_output
            
            if old_output:
                old_output.close()
                if hasattr(old_output, 'mp4_filepath') and os.path.exists(old_output.mp4_filepath):
                    self.metadata.update_chunk(old_output.mp4_filepath, old_frame_count)
            
            self.chunk_counter += 1
            logging.info(f"Started new chunk: {new_file}")
        except Exception as e:
            logging.error(f"Error during split recording: {str(e)}")

    def stop(self):
        self.recording = False
        if self.encoder and self.encoder.output:
            final_output = self.encoder.output
            final_output.close()
            if hasattr(final_output, 'mp4_filepath') and os.path.exists(final_output.mp4_filepath):
                self.metadata.update_chunk(final_output.mp4_filepath, final_output.frame_count)
        self.metadata.finalize(datetime.now())
