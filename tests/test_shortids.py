"""Tests for the done-command short-id mapping file.

write()/read() are pure I/O — no cache, no network, no credentials.
GTASK_SHORT_IDS_FILE points them at a temp file so these never touch the
developer's real ~/.gtask.
"""

import os
import tempfile
import unittest

from tasks_tui import shortids


class _MappingFileCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)  # start absent
        os.environ["GTASK_SHORT_IDS_FILE"] = self.path
        self.addCleanup(os.environ.pop, "GTASK_SHORT_IDS_FILE", None)
        self.addCleanup(self._remove_if_exists)

    def _remove_if_exists(self):
        if os.path.exists(self.path):
            os.remove(self.path)


class TestRoundTrip(_MappingFileCase):
    def test_write_then_read_round_trips(self):
        shortids.write({
            1: {"list_id": "L1", "task_id": "t1"},
            2: {"list_id": "L1", "task_id": "t2"},
        })
        mapping = shortids.read()
        self.assertEqual(mapping["1"], {"list_id": "L1", "task_id": "t1"})
        self.assertEqual(mapping["2"], {"list_id": "L1", "task_id": "t2"})

    def test_write_overwrites_the_previous_mapping(self):
        shortids.write({1: {"list_id": "L1", "task_id": "old"}})
        shortids.write({1: {"list_id": "L1", "task_id": "new"}})
        mapping = shortids.read()
        self.assertEqual(mapping["1"]["task_id"], "new")
        self.assertNotIn("2", mapping)

    def test_write_of_empty_mapping_is_a_valid_empty_result(self):
        shortids.write({})
        self.assertEqual(shortids.read(), {})

    def test_write_creates_the_parent_directory(self):
        nested = os.path.join(
            tempfile.mkdtemp(), "nested", "dir", "last_ids.json"
        )
        os.environ["GTASK_SHORT_IDS_FILE"] = nested
        shortids.write({1: {"list_id": "L1", "task_id": "t1"}})
        self.assertTrue(os.path.exists(nested))


class TestReadMissingOrMalformed(_MappingFileCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(shortids.read())

    def test_malformed_json_returns_none_not_a_crash(self):
        with open(self.path, "w") as f:
            f.write("{not valid json")
        self.assertIsNone(shortids.read())

    def test_valid_json_that_is_not_an_object_returns_none(self):
        with open(self.path, "w") as f:
            f.write("[1, 2, 3]")
        self.assertIsNone(shortids.read())


if __name__ == "__main__":
    unittest.main()
