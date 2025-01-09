import yaml
import logging
from pathlib import Path

def load_config(config_path='camera_config.yaml'):
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)