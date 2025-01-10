# rpicam

Continous video recording script for Raspberry Pi Camera Module 3. This script records and saves videos in chunks to avoid very large files, saves precise frame timestamps and metadata.

## Features

- Continuous video recording in configurable chunk lengths
- Automatic session management
- Detailed frame-by-frame timestamping
- Customizable camera settings via YAML configuration

## Installation

### Prerequisites

The script requires Python 3 and has been tested on Raspberry Pi OS. The picamera2 library typically comes pre-installed on Raspberry Pi. If not installed, install picamera2 first:
```bash
sudo apt-get update
sudo apt-get install -y python3-picamera2
```

### Dependencies

See requirements.txt for the full list of Python dependencies:
```text
picamera2>=0.3.12
pyyaml>=6.0.1
```

Install the required non-standard Python packages:
```bash
pip install -r requirements.txt
```

## Configuration

Camera settings are managed through `camera_config.yaml`. A template config file is included in this repository. Example configuration:
```yaml
# Subject name
subject_name: 'subject_name'

# Camera identification
pi_identifier: 'rpi_name'

# Camera settings
camera:
  # Basic settings
  brightness: 0.0  # Range: -1.0 to 1.0
  contrast: 1.5    # Range: 0.0 to 32.0
  saturation: 0.0  # Range: 0.0 to 32.0
  sharpness: 4.0   # Range: 0.0 to 16.0
  
  # Resolution
  resolution:
    width: 2304
    height: 1296
    
  # Format and exposure
  frame_format: 'YUV420'
  framerate: 10.0  # Range: 0.1 to 120.0
  
  # Additional controls
  analog_gain: 1.0       # Range: 1.0 to 16.0
  exposure_value: 0.0    # Range: -8.0 to 8.0
  noise_reduction: 3     # Range: 0 to 4

# Recording settings
recording:
  chunk_length: 3600  # seconds

# Storage settings
paths:
  video_save_path: '/path/to/videos'
  log_save_path: '/path/to/logs'
```

## Usage

After configuring the config file, run the recording script:
```bash
python record.py
```

The script will:
1. Create a new session directory with an automatically incremented session ID
2. Start recording video in chunks of the specified duration
3. Log detailed timestamps for each frame
4. Generate metadata files with recording information
5. Handle Ctrl+C gracefully for clean shutdown

### Output Structure

```
video_save_path/
└── <subject_name>_<YYYYMMDD>_<session_id>/
    ├── <subject_name>_<YYYYMMDD>_<session_id>_001.h264    # First video chunk
    ├── <subject_name>_<YYYYMMDD>_<session_id>_002.h264    # Second video chunk
    ├── <subject_name>_<YYYYMMDD>_<session_id>_metadata.yaml
    └── <subject_name>_<YYYYMMDD>_<session_id>_timestamps.txt
```

## Notes

- The script automatically manages session IDs based on the current date
- Video chunks are saved in H264 format. For many applications they should to be converted to mp4.
- Frame timestamps are saved in unix system time format.
- Metadata includes detailed information about each chunk.


