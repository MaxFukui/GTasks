"""Tests for the pure cache-query layer used by the CLI.

Every test builds a fake cache dict inline — the same shape
local_storage.load_data() returns — so nothing here touches the network,
credentials, or the filesystem.
"""

import datetime
import os
import time
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
                {"id": "t6", "title": "⭐Starred child", "status": "needsAction",
                 "parent": "t1"},
                {"id": "t7", "title": "⭐Deleted child", "status": "needsAction",
                 "parent": "t1", "deleted": True},
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
        # t3 and t6 are live children; deleted t7 is excluded.
        self.assertEqual(ids, ["t3", "t6"])

    def test_returns_empty_for_childless_parent(self):
        self.assertEqual(queries.subtasks(_cache(), "L1", "t2"), [])


class TestAllTasksForList(unittest.TestCase):
    def test_includes_subtasks_but_not_deleted(self):
        ids = [t["id"] for t in queries.all_tasks_for_list(_cache(), "L1")]
        self.assertEqual(ids, ["t1", "t2", "t3", "t6"])


class TestStarredTasks(unittest.TestCase):
    def test_returns_starred_across_all_lists_with_list_id(self):
        pairs = queries.starred_tasks(_cache())
        self.assertEqual(
            sorted((lid, t["id"]) for lid, t in pairs),
            [("L1", "t1"), ("L1", "t6"), ("L2", "t5")],
        )

    def test_excludes_unstarred(self):
        ids = [t["id"] for _, t in queries.starred_tasks(_cache())]
        self.assertNotIn("t2", ids)

    def test_includes_starred_subtasks(self):
        ids = [t["id"] for _, t in queries.starred_tasks(_cache())]
        self.assertIn("t6", ids)

    def test_excludes_unstarred_subtasks(self):
        ids = [t["id"] for _, t in queries.starred_tasks(_cache())]
        self.assertNotIn("t3", ids)

    def test_excludes_deleted_starred_subtasks(self):
        ids = [t["id"] for _, t in queries.starred_tasks(_cache())]
        self.assertNotIn("t7", ids)


class TestParentDisplayTitle(unittest.TestCase):
    def test_returns_parent_display_title_for_subtask(self):
        task = {"id": "t6", "title": "⭐Starred child", "parent": "t1"}
        self.assertEqual(
            queries.parent_display_title(_cache(), "L1", task), "Ship CLI"
        )

    def test_returns_none_for_top_level_task(self):
        task = {"id": "t1", "title": "⭐Ship CLI"}
        self.assertIsNone(queries.parent_display_title(_cache(), "L1", task))

    def test_returns_none_when_parent_missing(self):
        task = {"id": "x", "title": "orphan", "parent": "nope"}
        self.assertIsNone(queries.parent_display_title(_cache(), "L1", task))

    def test_with_parent_context_appends_separator(self):
        self.assertEqual(
            queries.with_parent_context("child", "parent"),
            "child  ·  parent",
        )

    def test_with_parent_context_leaves_title_alone_without_parent(self):
        self.assertEqual(queries.with_parent_context("child", None), "child")


class TestWithoutCompleted(unittest.TestCase):
    def test_drops_completed_tasks(self):
        tasks = queries.tasks_for_list(_cache(), "L1")
        ids = [t["id"] for t in queries.without_completed(tasks)]
        self.assertEqual(ids, ["t1"])


class TestResolveListName(unittest.TestCase):
    def _data(self):
        return {
            "task_lists": [
                {"id": "L1", "title": "Work"},
                {"id": "L2", "title": "Workout"},
                {"id": "L3", "title": "Home"},
            ],
            "tasks": {},
        }

    def test_exact_match_wins_over_prefix(self):
        # "Work" is also a prefix of "Workout"; exact must win.
        found = queries.resolve_list_name(self._data(), "Work")
        self.assertEqual(found["id"], "L1")

    def test_exact_match_is_case_insensitive(self):
        found = queries.resolve_list_name(self._data(), "wORK")
        self.assertEqual(found["id"], "L1")

    def test_unique_prefix_match(self):
        found = queries.resolve_list_name(self._data(), "ho")
        self.assertEqual(found["id"], "L3")

    def test_unique_substring_match(self):
        found = queries.resolve_list_name(self._data(), "ome")
        self.assertEqual(found["id"], "L3")

    def test_ambiguous_prefix_raises_with_candidates(self):
        with self.assertRaises(queries.ListResolutionError) as ctx:
            queries.resolve_list_name(self._data(), "wo")
        self.assertEqual(ctx.exception.candidates, ["Work", "Workout"])

    def test_no_match_raises_with_no_candidates(self):
        with self.assertRaises(queries.ListResolutionError) as ctx:
            queries.resolve_list_name(self._data(), "zzz")
        self.assertEqual(ctx.exception.candidates, [])

    def test_deleted_lists_are_not_resolvable(self):
        data = self._data()
        data["task_lists"].append({"id": "L4", "title": "Archive", "deleted": True})
        with self.assertRaises(queries.ListResolutionError):
            queries.resolve_list_name(data, "Archive")


class TestDueDate(unittest.TestCase):
    def test_reads_utc_date_component_without_conversion(self):
        # Google pins `due` to midnight UTC on the intended day. Converting
        # to local time would shift the date depending on the host's zone —
        # west of UTC loses a day, east of UTC doesn't. Pin both extremes so
        # this test fails on a stray `.astimezone()` regardless of the
        # machine it runs on, rather than only on machines west of UTC.
        original_tz = os.environ.get("TZ")

        def restore_tz():
            if original_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original_tz
            time.tzset()

        self.addCleanup(restore_tz)

        task = {"due": "2026-08-05T00:00:00.000Z"}
        for zone in ("Pacific/Kiritimati", "Pacific/Niue"):  # UTC+14, UTC-11
            with self.subTest(zone=zone):
                os.environ["TZ"] = zone
                time.tzset()
                self.assertEqual(queries.due_date(task), datetime.date(2026, 8, 5))

    def test_returns_none_when_no_due_field(self):
        self.assertIsNone(queries.due_date({"title": "x"}))

    def test_returns_none_for_unparseable_value(self):
        self.assertIsNone(queries.due_date({"due": "not-a-date"}))


class TestDueFilters(unittest.TestCase):
    def _tasks(self):
        return [
            {"id": "a", "due": "2026-08-04T00:00:00.000Z", "status": "needsAction"},
            {"id": "b", "due": "2026-08-05T00:00:00.000Z", "status": "needsAction"},
            {"id": "c", "due": "2026-08-03T00:00:00.000Z", "status": "needsAction"},
            {"id": "d", "due": "2026-08-03T00:00:00.000Z", "status": "completed"},
            {"id": "e", "status": "needsAction"},
        ]

    def test_due_on_matches_only_that_day(self):
        today = datetime.date(2026, 8, 4)
        ids = [t["id"] for t in queries.due_on(self._tasks(), today)]
        self.assertEqual(ids, ["a"])

    def test_due_on_ignores_tasks_with_no_due_date(self):
        today = datetime.date(2026, 8, 4)
        ids = [t["id"] for t in queries.due_on(self._tasks(), today)]
        self.assertNotIn("e", ids)

    def test_overdue_excludes_today_and_future(self):
        today = datetime.date(2026, 8, 4)
        ids = [t["id"] for t in queries.overdue(self._tasks(), today)]
        self.assertEqual(ids, ["c"])

    def test_overdue_excludes_completed_tasks(self):
        today = datetime.date(2026, 8, 4)
        ids = [t["id"] for t in queries.overdue(self._tasks(), today)]
        self.assertNotIn("d", ids)


class TestSearch(unittest.TestCase):
    def _tasks(self):
        return [
            {"id": "a", "title": "Buy milk"},
            {"id": "b", "title": "Call vet", "notes": "ask about milk allergy"},
            {"id": "c", "title": "Ship CLI"},
        ]

    def test_matches_title_case_insensitively(self):
        ids = [t["id"] for t in queries.search(self._tasks(), "MILK")]
        self.assertEqual(ids, ["a", "b"])

    def test_matches_notes(self):
        ids = [t["id"] for t in queries.search(self._tasks(), "allergy")]
        self.assertEqual(ids, ["b"])

    def test_no_match_returns_empty(self):
        self.assertEqual(queries.search(self._tasks(), "zzz"), [])


class TestAllTasksGlobal(unittest.TestCase):
    def test_tags_each_task_with_its_list(self):
        rows = queries.all_tasks_global(_cache())
        by_id = {t["id"]: t for t in rows}
        self.assertEqual(by_id["t1"]["_list_title"], "Work")
        self.assertEqual(by_id["t5"]["_list_id"], "L2")

    def test_includes_subtasks(self):
        ids = [t["id"] for t in queries.all_tasks_global(_cache())]
        self.assertIn("t3", ids)

    def test_does_not_mutate_the_cache(self):
        data = _cache()
        queries.all_tasks_global(data)
        self.assertNotIn("_list_id", data["tasks"]["L1"][0])


class TestToRow(unittest.TestCase):
    def test_strips_star_marker_into_a_flag(self):
        row = queries.to_row(
            {"title": "⭐Ship CLI", "status": "needsAction"}, "Work"
        )
        self.assertEqual(row["title"], "Ship CLI")
        self.assertTrue(row["starred"])

    def test_marks_completed_tasks_done(self):
        row = queries.to_row({"title": "x", "status": "completed"}, "Work")
        self.assertTrue(row["done"])

    def test_carries_due_date_and_depth(self):
        row = queries.to_row(
            {"title": "x", "due": "2026-08-05T00:00:00.000Z"}, "Work", depth=1
        )
        self.assertEqual(row["due"], datetime.date(2026, 8, 5))
        self.assertEqual(row["depth"], 1)

    def test_carries_the_original_task_as_raw(self):
        task = {
            "id": "t1",
            "title": "⭐Ship CLI",
            "status": "needsAction",
            "notes": "ship it",
            "_list_id": "L1",
        }
        row = queries.to_row(task, "Work")
        self.assertEqual(row["raw"], task)

    def test_raw_does_not_change_the_six_existing_keys(self):
        task = {"title": "⭐Ship CLI", "status": "needsAction"}
        row = queries.to_row(task, "Work")
        self.assertEqual(
            set(row) - {"raw"},
            {"title", "done", "due", "starred", "list_title", "depth"},
        )


if __name__ == "__main__":
    unittest.main()
