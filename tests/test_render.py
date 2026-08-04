"""Tests for the three output modes.

Pretty output is for a terminal, plain is for pipes, json is for scripts.
The renderer is pure: rows in, string out.
"""

import datetime
import json
import unittest

from tasks_tui import render


def _rows():
    return [
        {
            "title": "Ship CLI",
            "done": False,
            "due": datetime.date(2026, 8, 5),
            "starred": True,
            "list_title": "Work",
            "depth": 0,
        },
        {
            "title": "Review PR",
            "done": True,
            "due": None,
            "starred": False,
            "list_title": "Work",
            "depth": 0,
        },
        {
            "title": "Buy milk",
            "done": False,
            "due": None,
            "starred": True,
            "list_title": "Home",
            "depth": 0,
        },
    ]


class TestPickMode(unittest.TestCase):
    def test_tty_gives_pretty(self):
        self.assertEqual(
            render.pick_mode(is_tty=True, want_json=False, no_color=False),
            render.PRETTY,
        )

    def test_pipe_gives_plain(self):
        self.assertEqual(
            render.pick_mode(is_tty=False, want_json=False, no_color=False),
            render.PLAIN,
        )

    def test_no_color_forces_plain_even_on_tty(self):
        self.assertEqual(
            render.pick_mode(is_tty=True, want_json=False, no_color=True),
            render.PLAIN,
        )

    def test_json_overrides_everything(self):
        self.assertEqual(
            render.pick_mode(is_tty=True, want_json=True, no_color=False),
            render.JSON,
        )


class TestPlain(unittest.TestCase):
    def test_one_row_per_line_with_checkbox_list_and_due(self):
        out = render.render(_rows(), render.PLAIN, group_by_list=True)
        self.assertEqual(
            out.splitlines(),
            [
                "[ ] Ship CLI   (Work)  due 2026-08-05",
                "[x] Review PR  (Work)",
                "[ ] Buy milk   (Home)",
            ],
        )

    def test_contains_no_ansi_escapes(self):
        out = render.render(_rows(), render.PLAIN, group_by_list=True)
        self.assertNotIn("\x1b", out)

    def test_omits_list_column_when_not_grouping(self):
        out = render.render(_rows()[:1], render.PLAIN, group_by_list=False)
        self.assertEqual(out, "[ ] Ship CLI  due 2026-08-05")

    def test_empty_rows_render_empty_string(self):
        self.assertEqual(render.render([], render.PLAIN, group_by_list=True), "")


class TestPretty(unittest.TestCase):
    def test_groups_under_list_headers(self):
        out = render.render(_rows(), render.PRETTY, group_by_list=True)
        lines = [ln for ln in out.splitlines() if ln]
        self.assertIn("Work", lines[0])
        self.assertIn("Ship CLI", lines[1])
        self.assertIn("Home", lines[3])

    def test_uses_open_and_done_glyphs(self):
        out = render.render(_rows(), render.PRETTY, group_by_list=True)
        self.assertIn("○", out)
        self.assertIn("●", out)

    def test_indents_subtasks_by_depth(self):
        rows = [dict(_rows()[0], depth=1, starred=False)]
        out = render.render(rows, render.PRETTY, group_by_list=False)
        self.assertTrue(out.startswith("    "))

    def test_overdue_and_not_done_renders_red(self):
        rows = [_rows()[0]]  # due 2026-08-05, not done
        out = render.render(
            rows,
            render.PRETTY,
            group_by_list=False,
            today=datetime.date(2026, 8, 6),
        )
        self.assertIn("\x1b[31m", out)

    def test_not_yet_due_does_not_render_red(self):
        rows = [_rows()[0]]  # due 2026-08-05, not done
        out = render.render(
            rows,
            render.PRETTY,
            group_by_list=False,
            today=datetime.date(2026, 8, 1),
        )
        self.assertNotIn("\x1b[31m", out)

    def test_done_and_overdue_does_not_render_red(self):
        rows = [dict(_rows()[0], done=True)]  # due 2026-08-05, but done
        out = render.render(
            rows,
            render.PRETTY,
            group_by_list=False,
            today=datetime.date(2026, 8, 6),
        )
        self.assertNotIn("\x1b[31m", out)


class TestJson(unittest.TestCase):
    def test_payload_carries_tasks_and_sync_info(self):
        info = {
            "last_sync": "2026-08-04T09:00:00.000Z",
            "stale_seconds": 10800,
            "approx": False,
        }
        payload = json.loads(
            render.render(_rows(), render.JSON, group_by_list=True, sync_info=info)
        )
        self.assertEqual(payload["stale_seconds"], 10800)
        self.assertEqual(len(payload["tasks"]), 3)

    def test_due_dates_are_iso_strings(self):
        payload = json.loads(
            render.render(_rows(), render.JSON, group_by_list=True)
        )
        self.assertEqual(payload["tasks"][0]["due"], "2026-08-05")
        self.assertIsNone(payload["tasks"][1]["due"])

    def test_starred_is_a_boolean_not_a_title_marker(self):
        payload = json.loads(
            render.render(_rows(), render.JSON, group_by_list=True)
        )
        self.assertTrue(payload["tasks"][0]["starred"])
        self.assertNotIn("⭐", payload["tasks"][0]["title"])


class TestRenderLists(unittest.TestCase):
    def _entries(self):
        return [
            {"title": "Work", "undone": 2, "total": 5},
            {"title": "Home", "undone": 0, "total": 1},
        ]

    def test_plain_shows_counts(self):
        out = render.render_lists(self._entries(), render.PLAIN)
        self.assertEqual(out.splitlines(), ["Work  2/5", "Home  0/1"])

    def test_json_shows_counts(self):
        payload = json.loads(render.render_lists(self._entries(), render.JSON))
        self.assertEqual(payload["lists"][0]["undone"], 2)


if __name__ == "__main__":
    unittest.main()
