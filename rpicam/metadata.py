import os
import yaml
from datetime import datetime

class SessionMetadata:
    def __init__(self, subject_path, start_time, config):
        session_folder = os.path.basename(subject_path)
        folder_parts = session_folder.split('_')
        
        self.filepath = os.path.join(
            subject_path,
            f"{session_folder}_{config['pi_identifier']}_metadata.yaml"
        )
        self.metadata = {
            'recording': {
                'subject_name': folder_parts[0],
                'recording_date': folder_parts[1],
                'session_id': int(folder_parts[2]),
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
    
    def update_chunk(self, mp4_file, total_frames):
        """Update metadata with new chunk information and total frame count"""
        if mp4_file not in self.metadata['recording']['video_files']:
            self.metadata['recording']['video_files'].append(mp4_file)
        self.metadata['recording']['total_frames'] = total_frames
        self.save()
        logging.info(f"Metadata updated - Added file: {mp4_file}, Total frames: {total_frames}")
    
    def finalize(self, end_time):
        self.metadata['recording']['end_time'] = end_time.isoformat()
        self.save()
    
    def save(self):
        with open(self.filepath, 'w') as f:
            yaml.dump(self.metadata, f, default_flow_style=False)
