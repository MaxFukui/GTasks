"""Tests for local_storage's path resolution.

load_data()/save_data() must honor GTASK_CACHE_FILE (via cache_path()), the
same override cli.py's read-only verbs already use — otherwise anything
that writes through TaskService (sync, done) touches the developer's real
~/.gtask/local_tasks.json instead of a test fixture.
"""

import json
import os
import tempfile
import unittest

from tasks_tui import local_storage


class _CacheOverrideCase(unittest.TestCase):
    def setUp(self):
        fd, self.cache_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.cache_file)  # start absent; load_data must handle that
        os.environ["GTASK_CACHE_FILE"] = self.cache_file
        self.addCleanup(os.environ.pop, "GTASK_CACHE_FILE", None)
        self.addCleanup(self._remove_if_exists)

    def _remove_if_exists(self):
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)


class TestLoadDataHonorsOverride(_CacheOverrideCase):
    def test_missing_override_file_returns_empty_shape(self):
        self.assertEqual(
            local_storage.load_data(), {"task_lists": [], "tasks": {}}
        )

    def test_reads_the_override_file_not_the_real_cache(self):
        with open(self.cache_file, "w") as f:
            json.dump({"task_lists": [{"id": "L1"}], "tasks": {}}, f)
        data = local_storage.load_data()
        self.assertEqual(data["task_lists"], [{"id": "L1"}])


class TestSaveDataHonorsOverride(_CacheOverrideCase):
    def test_writes_to_the_override_file_not_the_real_cache(self):
        local_storage.save_data({"task_lists": [{"id": "L9"}], "tasks": {}})
        with open(self.cache_file) as f:
            written = json.load(f)
        self.assertEqual(written["task_lists"], [{"id": "L9"}])

    def test_round_trips_through_load_data(self):
        payload = {"task_lists": [{"id": "L2"}], "tasks": {"L2": []}}
        local_storage.save_data(payload)
        self.assertEqual(local_storage.load_data(), payload)


class TestSaveDataReturnValue(_CacheOverrideCase):
    """save_data() must tell the caller whether the write actually reached
    disk, so TaskService.save_local_data() can avoid claiming success when
    the local write also failed (e.g. after a sync failure)."""

    def test_returns_true_on_a_successful_write(self):
        result = local_storage.save_data({"task_lists": [], "tasks": {}})
        self.assertTrue(result)

    def test_returns_false_when_the_write_raises(self):
        # Point the override at a path whose parent directory does not
        # exist — open(..., "w") raises FileNotFoundError, a subclass of
        # OSError/IOError, which save_data() must catch and report via its
        # return value instead of silently swallowing.
        os.environ["GTASK_CACHE_FILE"] = os.path.join(
            tempfile.mkdtemp(), "no-such-dir", "cache.json"
        )
        result = local_storage.save_data({"task_lists": [], "tasks": {}})
        self.assertFalse(result)


class TestShortIdsPath(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, "GTASK_SHORT_IDS_FILE", None)

    def test_defaults_under_gtask_dir(self):
        os.environ.pop("GTASK_SHORT_IDS_FILE", None)
        path = local_storage.short_ids_path()
        self.assertTrue(path.endswith("last_ids.json"))
        self.assertIn(".gtask", path)

    def test_honors_override(self):
        os.environ["GTASK_SHORT_IDS_FILE"] = "/tmp/custom_ids.json"
        self.assertEqual(
            local_storage.short_ids_path(), "/tmp/custom_ids.json"
        )


if __name__ == "__main__":
    unittest.main()
