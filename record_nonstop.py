import os
import sys
import signal
import logging
import time
from datetime import datetime

from rpicam.config import load_config
from rpicam.utils import get_next_session_id, get_session_folder_name, ensure_directory_exists
from rpicam.video_output import VideoOutput
from rpicam.recorder import ContinuousRecording
from rpicam.camera_manager import setup_camera, create_encoder

def handle_shutdown(camera, recorder):
    print("\nInitiating safe shutdown...")
    try:
        if recorder:
            recorder.stop()
            logging.info("Recorder stopped")
        
        time.sleep(0.5)  # Short delay before stopping camera
        
        if camera:
            camera.stop_recording()
            camera.close()  # Explicitly close the camera
            logging.info("Camera recording stopped and closed")
        
        time.sleep(0.5)  # Give time for final cleanup
        logging.shutdown()
        print("Shutdown complete. All files have been saved.")
    except Exception as e:
        logging.exception("Error during shutdown")
        print(f"Error during shutdown: {str(e)}")
    finally:
        os._exit(0)

def main():
    try:
        config = load_config()
        recording_date = datetime.now().strftime('%Y%m%d')
        
        base_video_path = config['paths']['video_save_path']
        subject_name = config['subject_name']
        session_id = get_next_session_id(base_video_path, subject_name, recording_date)
        
        session_folder = get_session_folder_name(subject_name, recording_date, session_id)
        subject_path = os.path.join(base_video_path, session_folder)
        ensure_directory_exists(subject_path)
        
        log_file = os.path.join(
            subject_path,
            f"{session_folder}_{config['pi_identifier']}.log"
        )
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s:%(levelname)s:%(message)s'
        )
        
        logging.info(f"Starting recording session {session_id}")

        camera = setup_camera(config)
        start_time = datetime.now()
        
        initial_chunk = 1
        first_file = os.path.join(
            subject_path,
            f"{session_folder}_{config['pi_identifier']}_chunk{initial_chunk:03d}.h264"
        )
        
        output = VideoOutput(first_file, config)
        encoder = create_encoder(config)
        encoder.output = output
        
        camera.start_recording(encoder=encoder, output=output)
        recorder = ContinuousRecording(
            camera, 
            encoder, 
            subject_path, 
            start_time, 
            config,
            initial_chunk=initial_chunk  # Pass the initial chunk number
        )
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