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
SHORT_IDS_FILE = os.path.join(GTASK_DIR, "last_ids.json")


def cache_path():
    """Path to the task cache. GTASK_CACHE_FILE overrides it, which is how
    tests point the CLI at a fixture without touching the real ~/.gtask."""
    return os.environ.get("GTASK_CACHE_FILE", STORAGE_FILE)


def short_ids_path():
    """Path to the done-command short-id mapping. GTASK_SHORT_IDS_FILE
    overrides it, the same pattern cache_path()/GTASK_CACHE_FILE already
    uses, so tests never touch the real ~/.gtask."""
    return os.environ.get("GTASK_SHORT_IDS_FILE", SHORT_IDS_FILE)


def _ensure_dir_exists():
    """Ensures that the .gtask directory exists."""
    if not os.path.exists(GTASK_DIR):
        os.makedirs(GTASK_DIR)


def load_data():
    """Loads task data from the local JSON storage file."""
    _ensure_dir_exists()
    path = cache_path()
    if not os.path.exists(path):
        return {"task_lists": [], "tasks": {}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"task_lists": [], "tasks": {}}


def save_data(data):
    """Saves task data to the local JSON storage file.

    Returns True if the write reached disk, False if it failed (e.g.
    permissions, full disk, unwritable parent) — callers that need to know
    whether the save actually persisted (TaskService.save_local_data) rely
    on this instead of assuming success.
    """
    _ensure_dir_exists()
    try:
        with open(cache_path(), "w") as f:
            json.dump(data, f, indent=4)
    except IOError:
        # Handle cases where the file cannot be written
        return False
    return True


def load_config():
    """Loads user configuration from the local JSON config file."""
    _ensure_dir_exists()
    if not os.path.exists(CONFIG_FILE):
        return {
            "hide_completed": False,
            "active_list_id": None,
            "list_order": [],
            "show_tracker": True,
        }
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            "hide_completed": False,
            "active_list_id": None,
            "list_order": [],
            "show_tracker": True,
        }


def save_config(config):
    """Saves user configuration to the local JSON config file."""
    _ensure_dir_exists()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except IOError:
        pass
