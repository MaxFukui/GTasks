"""Ephemeral number -> (list_id, task_id) mapping for `tasks-tui done <N>`.

Every listing verb (fav, list, today, overdue, search) overwrites this file
after it finishes rendering, so a number always means "row N of the most
recent listing" and never anything older. Pure I/O — no cache logic, no
network, no credentials.
"""

import json
import os

from . import local_storage


def write(mapping):
    """Overwrites the mapping file. `mapping` is {int: {"list_id": str,
    "task_id": str}}; json.dump stringifies the int keys automatically, so
    read() always sees string keys back."""
    path = local_storage.short_ids_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2)


def read():
    """Returns the mapping (string keys) or None if the file is missing,
    is not valid JSON, or is not a JSON object."""
    path = local_storage.short_ids_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
