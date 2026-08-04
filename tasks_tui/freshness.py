"""How stale is the local cache?

The CLI reads the cache without touching the network, so every query tells
the user how old that data is. The signal is the `last_sync` key written by
TaskService's two sync methods — not the cache file's mtime, which changes on
every local edit and would therefore report "just synced" after an offline
change.
"""

import datetime
import os

from dateutil.parser import isoparse

STALE_AFTER_SECONDS = 24 * 60 * 60


def sync_info(data, cache_path, now=None):
    """Returns {last_sync, stale_seconds, approx} for a loaded cache.

    Falls back to the cache file's mtime when the cache predates the
    `last_sync` key, flagging the result as approximate. Both missing means
    the cache has never been synced.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)

    raw = data.get("last_sync")
    if raw:
        try:
            stamp = isoparse(raw)
            return {
                "last_sync": raw,
                "stale_seconds": int((now - stamp).total_seconds()),
                "approx": False,
            }
        except (ValueError, OverflowError, TypeError):
            pass  # fall through to the mtime fallback

    try:
        mtime = os.path.getmtime(cache_path)
    except OSError:
        return {"last_sync": None, "stale_seconds": None, "approx": False}

    stamp = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
    return {
        "last_sync": stamp.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "stale_seconds": int((now - stamp).total_seconds()),
        "approx": True,
    }


def _humanize(seconds):
    if seconds < 60:
        return None  # caller special-cases "just now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def format_age(info):
    """One-line staleness footer, e.g. 'synced 3h ago'."""
    seconds = info.get("stale_seconds")
    if seconds is None:
        return "never synced — run 'tasks-tui sync'"

    span = _humanize(seconds)
    if span is None:
        return "synced just now"

    if info.get("approx"):
        return f"synced ~{span} ago (approx)"
    if seconds >= STALE_AFTER_SECONDS:
        return f"synced {span} ago — run 'tasks-tui sync'"
    return f"synced {span} ago"
