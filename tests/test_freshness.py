"""Tests for cache-staleness reporting.

The CLI prints how long it has been since the cache last talked to Google.
These tests pin the clock rather than sleeping.
"""

import datetime
import os
import tempfile
import unittest

from tasks_tui import freshness


def _iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


NOW = datetime.datetime(2026, 8, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)


class TestSyncInfo(unittest.TestCase):
    def test_reads_last_sync_key(self):
        data = {"last_sync": _iso(NOW - datetime.timedelta(hours=3))}
        info = freshness.sync_info(data, "/nonexistent", now=NOW)
        self.assertEqual(info["stale_seconds"], 10800)
        self.assertFalse(info["approx"])

    def test_falls_back_to_file_mtime_and_marks_approx(self):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            path = tf.name
        mtime = (NOW - datetime.timedelta(hours=2)).timestamp()
        os.utime(path, (mtime, mtime))
        try:
            info = freshness.sync_info({}, path, now=NOW)
            self.assertEqual(info["stale_seconds"], 7200)
            self.assertTrue(info["approx"])
        finally:
            os.remove(path)

    def test_no_key_and_no_file_reports_never_synced(self):
        info = freshness.sync_info({}, "/nonexistent", now=NOW)
        self.assertIsNone(info["stale_seconds"])
        self.assertIsNone(info["last_sync"])

    def test_unparseable_last_sync_falls_back(self):
        info = freshness.sync_info({"last_sync": "garbage"}, "/nonexistent", now=NOW)
        self.assertIsNone(info["stale_seconds"])


class TestFormatAge(unittest.TestCase):
    def test_under_a_minute_says_just_now(self):
        self.assertEqual(
            freshness.format_age({"stale_seconds": 30, "approx": False}),
            "synced just now",
        )

    def test_hours(self):
        self.assertEqual(
            freshness.format_age({"stale_seconds": 10800, "approx": False}),
            "synced 3h ago",
        )

    def test_minutes(self):
        self.assertEqual(
            freshness.format_age({"stale_seconds": 300, "approx": False}),
            "synced 5m ago",
        )

    def test_over_a_day_nudges_to_sync(self):
        self.assertEqual(
            freshness.format_age({"stale_seconds": 172800, "approx": False}),
            "synced 2d ago — run 'tasks-tui sync'",
        )

    def test_approx_is_marked(self):
        self.assertEqual(
            freshness.format_age({"stale_seconds": 10800, "approx": True}),
            "synced ~3h ago (approx)",
        )

    def test_never_synced(self):
        self.assertEqual(
            freshness.format_age({"stale_seconds": None, "approx": False}),
            "never synced — run 'tasks-tui sync'",
        )


if __name__ == "__main__":
    unittest.main()
