import os
import logging
from datetime import datetime

def get_next_session_id(base_path, subject_name, recording_date):
    """
    Scan the base directory for existing session folders and return the next available session ID.
    Format: subject_YYYYMMDD_XX
    """
    try:
        folder_prefix = f"{subject_name}_{recording_date}"
        existing_sessions = []
        if os.path.exists(base_path):
            for dirname in os.listdir(base_path):
                if dirname.startswith(folder_prefix):
                    try:
                        session_id = int(dirname.split('_')[-1])
                        existing_sessions.append(session_id)
                    except (ValueError, IndexError):
                        continue
        
        return 1 if not existing_sessions else max(existing_sessions) + 1
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
