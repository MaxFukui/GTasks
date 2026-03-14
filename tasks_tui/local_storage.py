import os
import json

# Get the user's home directory
HOME_DIR = os.path.expanduser("~")
# Define the directory to store the data
GTASK_DIR = os.path.join(HOME_DIR, ".gtask")
# Define the storage file path
STORAGE_FILE = os.path.join(GTASK_DIR, "local_tasks.json")
# Define the config file path
CONFIG_FILE = os.path.join(GTASK_DIR, "config.json")


def _ensure_dir_exists():
    """Ensures that the .gtask directory exists."""
    if not os.path.exists(GTASK_DIR):
        os.makedirs(GTASK_DIR)


def load_data():
    """Loads task data from the local JSON storage file."""
    _ensure_dir_exists()
    if not os.path.exists(STORAGE_FILE):
        return {"task_lists": [], "tasks": {}}
    try:
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"task_lists": [], "tasks": {}}


def save_data(data):
    """Saves task data to the local JSON storage file."""
    _ensure_dir_exists()
    try:
        with open(STORAGE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except IOError:
        # Handle cases where the file cannot be written
        pass


def load_config():
    """Loads user configuration from the local JSON config file."""
    _ensure_dir_exists()
    if not os.path.exists(CONFIG_FILE):
        return {"hide_completed": False, "active_list_id": None, "list_order": []}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"hide_completed": False, "active_list_id": None, "list_order": []}


def save_config(config):
    """Saves user configuration to the local JSON config file."""
    _ensure_dir_exists()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except IOError:
        pass
