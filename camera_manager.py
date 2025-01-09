from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from libcamera import controls

def setup_camera(config):
    camera = Picamera2()
    
    video_config = camera.create_video_configuration(
        main={
            "size": (
                config['camera']['resolution']['width'],
                config['camera']['resolution']['height']
            ),
            "format": "YUV420"
        },
        encode="main"
    )
    
    camera.configure(video_config)
    
    controls_dict = {
        "AfMode": controls.AfModeEnum.Manual,
        "LensPosition": config['camera']['lens']['position'],
        "FrameDurationLimits": tuple(config['camera']['frame_duration_limits']),
        "Brightness": config['camera']['brightness'],
        "Contrast": config['camera']['contrast'],
        "Saturation": 0.0,
        "AwbEnable": False
    }
    
    camera.set_controls(controls_dict)
    return camera

def create_encoder(config):
    encoder = H264Encoder()
    encoder.repeat_sequence_header = True
    encoder.inline_headers = True
    encoder.bitrate = config['camera']['bitrate']
    return encoder