"""Tests for stable short ids derived from Google task ids.

No filesystem, no network — short_id/resolve/normalize_token are pure.
"""

import hashlib
import unittest

from tasks_tui import shortids


def _sha_prefix(task_id, n=shortids.DISPLAY_LEN):
    return hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:n]


class TestShortId(unittest.TestCase):
    def test_is_deterministic(self):
        self.assertEqual(shortids.short_id("t1"), shortids.short_id("t1"))

    def test_is_display_len_hex(self):
        handle = shortids.short_id("t1")
        self.assertEqual(len(handle), shortids.DISPLAY_LEN)
        self.assertTrue(all(c in "0123456789abcdef" for c in handle))

    def test_matches_sha1_prefix(self):
        self.assertEqual(shortids.short_id("t1"), _sha_prefix("t1"))

    def test_empty_id_returns_empty_string(self):
        self.assertEqual(shortids.short_id(""), "")
        self.assertEqual(shortids.short_id(None), "")

    def test_different_ids_usually_differ(self):
        self.assertNotEqual(shortids.short_id("t1"), shortids.short_id("t2"))


class TestNormalizeToken(unittest.TestCase):
    def test_lowercases_and_accepts_min_length(self):
        self.assertEqual(shortids.normalize_token("A3F"), "a3f")

    def test_accepts_longer_than_display(self):
        self.assertEqual(shortids.normalize_token("a3f1b"), "a3f1b")

    def test_rejects_too_short(self):
        self.assertIsNone(shortids.normalize_token("a3"))
        self.assertIsNone(shortids.normalize_token(""))

    def test_rejects_non_hex(self):
        self.assertIsNone(shortids.normalize_token("zzzz"))
        self.assertIsNone(shortids.normalize_token("ship"))


class TestResolve(unittest.TestCase):
    def _data(self):
        return {
            "task_lists": [
                {"id": "L1", "title": "Work"},
                {"id": "L2", "title": "Home"},
                {"id": "L3", "title": "Gone", "deleted": True},
            ],
            "tasks": {
                "L1": [
                    {"id": "t1", "title": "Ship CLI", "status": "needsAction"},
                    {"id": "t2", "title": "Review", "status": "needsAction"},
                    {"id": "gone", "title": "Deleted", "deleted": True},
                ],
                "L2": [
                    {"id": "t3", "title": "Buy milk", "status": "needsAction"},
                ],
                "L3": [
                    {"id": "t4", "title": "In deleted list", "status": "needsAction"},
                ],
            },
        }

    def test_exact_short_finds_the_task(self):
        data = self._data()
        handle = shortids.short_id("t1")
        hits = shortids.resolve(data, handle)
        self.assertEqual([(lid, t["id"]) for lid, t in hits], [("L1", "t1")])

    def test_prefix_match_when_unique(self):
        data = self._data()
        handle = shortids.short_id("t1")
        hits = shortids.resolve(data, handle[:3])
        # May or may not be unique depending on hash; at least includes t1.
        ids = [t["id"] for _, t in hits]
        self.assertIn("t1", ids)

    def test_excludes_deleted_tasks_and_lists(self):
        data = self._data()
        gone_handle = shortids.short_id("gone")
        self.assertEqual(shortids.resolve(data, gone_handle), [])
        t4_handle = shortids.short_id("t4")
        self.assertEqual(shortids.resolve(data, t4_handle), [])

    def test_no_match_returns_empty(self):
        # 3 hex chars extremely unlikely to match our three live shorts.
        self.assertEqual(shortids.resolve(self._data(), "000"), [])


if __name__ == "__main__":
    unittest.main()
