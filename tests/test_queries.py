"""Tests for the pure cache-query layer used by the CLI.

Every test builds a fake cache dict inline — the same shape
local_storage.load_data() returns — so nothing here touches the network,
credentials, or the filesystem.
"""

import unittest

from tasks_tui import queries


def _cache():
    """A small fixture cache: two lists, a mix of task states."""
    return {
        "task_lists": [
            {"id": "L1", "title": "Work"},
            {"id": "L2", "title": "Home"},
            {"id": "L3", "title": "Old", "deleted": True},
        ],
        "tasks": {
            "L1": [
                {"id": "t1", "title": "⭐Ship CLI", "status": "needsAction"},
                {"id": "t2", "title": "Review PR", "status": "completed"},
                {"id": "t3", "title": "Subtask", "status": "needsAction",
                 "parent": "t1"},
                {"id": "t4", "title": "Gone", "status": "needsAction",
                 "deleted": True},
            ],
            "L2": [
                {"id": "t5", "title": "⭐Buy milk", "status": "needsAction"},
            ],
        },
    }


class TestStarHelpers(unittest.TestCase):
    def test_is_starred_true_for_marked_title(self):
        self.assertTrue(queries.is_starred({"title": "⭐Ship CLI"}))

    def test_is_starred_false_for_plain_title(self):
        self.assertFalse(queries.is_starred({"title": "Ship CLI"}))

    def test_display_title_strips_marker(self):
        self.assertEqual(
            queries.display_title({"title": "⭐Ship CLI"}), "Ship CLI"
        )

    def test_display_title_leaves_plain_title_alone(self):
        self.assertEqual(
            queries.display_title({"title": "Ship CLI"}), "Ship CLI"
        )


class TestTaskLists(unittest.TestCase):
    def test_excludes_deleted_lists(self):
        ids = [lst["id"] for lst in queries.task_lists(_cache())]
        self.assertEqual(ids, ["L1", "L2"])

    def test_applies_list_order(self):
        ids = [
            lst["id"]
            for lst in queries.task_lists(_cache(), list_order=["L2", "L1"])
        ]
        self.assertEqual(ids, ["L2", "L1"])

    def test_unknown_lists_sort_last(self):
        ids = [
            lst["id"] for lst in queries.task_lists(_cache(), list_order=["L2"])
        ]
        self.assertEqual(ids, ["L2", "L1"])


class TestTasksForList(unittest.TestCase):
    def test_returns_top_level_only(self):
        ids = [t["id"] for t in queries.tasks_for_list(_cache(), "L1")]
        self.assertEqual(ids, ["t1", "t2"])

    def test_excludes_deleted_tasks(self):
        ids = [t["id"] for t in queries.tasks_for_list(_cache(), "L1")]
        self.assertNotIn("t4", ids)

    def test_unknown_list_returns_empty(self):
        self.assertEqual(queries.tasks_for_list(_cache(), "nope"), [])


class TestSubtasks(unittest.TestCase):
    def test_returns_children_of_parent(self):
        ids = [t["id"] for t in queries.subtasks(_cache(), "L1", "t1")]
        self.assertEqual(ids, ["t3"])

    def test_returns_empty_for_childless_parent(self):
        self.assertEqual(queries.subtasks(_cache(), "L1", "t2"), [])


class TestAllTasksForList(unittest.TestCase):
    def test_includes_subtasks_but_not_deleted(self):
        ids = [t["id"] for t in queries.all_tasks_for_list(_cache(), "L1")]
        self.assertEqual(ids, ["t1", "t2", "t3"])


class TestStarredTasks(unittest.TestCase):
    def test_returns_starred_across_all_lists_with_list_id(self):
        pairs = queries.starred_tasks(_cache())
        self.assertEqual(
            sorted((lid, t["id"]) for lid, t in pairs),
            [("L1", "t1"), ("L2", "t5")],
        )

    def test_excludes_unstarred(self):
        ids = [t["id"] for _, t in queries.starred_tasks(_cache())]
        self.assertNotIn("t2", ids)


class TestWithoutCompleted(unittest.TestCase):
    def test_drops_completed_tasks(self):
        tasks = queries.tasks_for_list(_cache(), "L1")
        ids = [t["id"] for t in queries.without_completed(tasks)]
        self.assertEqual(ids, ["t1"])


if __name__ == "__main__":
    unittest.main()
