"""Stable short ids derived from Google task ids.

Listings show a 4-char hex handle; `tasks-tui done <short>` accepts any
prefix of at least MIN_INPUT_LEN characters. Resolution scans the local
cache — nothing is written on list, and the handle does not change across
listings the way the old ephemeral row numbers did.
"""

import hashlib

DISPLAY_LEN = 4
MIN_INPUT_LEN = 3
_HEX = set("0123456789abcdef")


def short_id(task_id):
    """4-char hex short derived from a Google task id.

    Pure function of the id: same task always gets the same short, no
    side table required. Empty/missing ids yield an empty string so callers
    can skip decorating a row rather than printing a bogus handle.
    """
    if not task_id:
        return ""
    digest = hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()
    return digest[:DISPLAY_LEN]


def normalize_token(token):
    """Lowercases and strips a user-typed short. Returns None if unusable.

    Rejects empty tokens, tokens shorter than MIN_INPUT_LEN, and anything
    outside hex — so `done` never accidentally treats a title fragment as
    an id.
    """
    if token is None:
        return None
    cleaned = str(token).strip().lower()
    if len(cleaned) < MIN_INPUT_LEN:
        return None
    if any(ch not in _HEX for ch in cleaned):
        return None
    return cleaned


def resolve(data, token):
    """All non-deleted (list_id, task) whose short id starts with `token`.

    `token` must already be normalized (lowercase hex, length >= MIN_INPUT_LEN).
    Order follows list order then cache order within each list, so a
    disambiguation prompt is stable across runs for the same cache.
    """
    if not token:
        return []
    hits = []
    for task_list in data.get("task_lists", []):
        if task_list.get("deleted"):
            continue
        list_id = task_list.get("id")
        if not list_id:
            continue
        for task in data.get("tasks", {}).get(list_id, []):
            if task.get("deleted"):
                continue
            handle = short_id(task.get("id"))
            if handle.startswith(token):
                hits.append((list_id, task))
    return hits
