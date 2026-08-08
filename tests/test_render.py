"""Tests for the three output modes.

Pretty output is for a terminal, plain is for pipes, json is for scripts.
The renderer is pure: rows in, string out.
"""

import datetime
import json
import re
import unittest

from tasks_tui import render

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)


def _rows():
    return [
        {
            "title": "Ship CLI",
            "done": False,
            "due": datetime.date(2026, 8, 5),
            "starred": True,
            "list_title": "Work",
            "depth": 0,
            "raw": {
                "id": "t1",
                "title": "⭐Ship CLI",
                "status": "needsAction",
                "due": "2026-08-05T00:00:00.000Z",
                "notes": "ship it",
                "_list_id": "L1",
                "_list_title": "Work",
            },
        },
        {
            "title": "Review PR",
            "done": True,
            "due": None,
            "starred": False,
            "list_title": "Work",
            "depth": 0,
            "raw": {
                "id": "t2",
                "title": "Review PR",
                "status": "completed",
                "_list_id": "L1",
                "_list_title": "Work",
            },
        },
        {
            "title": "Buy milk",
            "done": False,
            "due": None,
            "starred": True,
            "list_title": "Home",
            "depth": 0,
            "raw": {
                "id": "t3",
                "title": "⭐Buy milk",
                "status": "needsAction",
                "_list_id": "L2",
                "_list_title": "Home",
            },
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
        self.assertTrue(_strip_ansi(out).startswith("    "))

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

    def test_short_ids_are_not_printed_when_absent_from_the_row(self):
        out = render.render(_rows(), render.PRETTY, group_by_list=True)
        # No hex handle column when rows lack short_id.
        plain = _strip_ansi(out)
        first_task = next(
            ln for ln in plain.splitlines() if "Ship CLI" in ln
        )
        self.assertTrue(first_task.lstrip().startswith("○"))

    def test_prints_the_short_id_when_present(self):
        rows = [dict(_rows()[0], short_id="a3f1")]
        out = render.render(rows, render.PRETTY, group_by_list=False)
        plain = _strip_ansi(out)
        self.assertTrue(plain.lstrip().startswith("a3f1"))

    def test_short_ids_appear_across_group_headers(self):
        rows = [
            dict(_rows()[0], short_id="aaaa"),  # Work
            dict(_rows()[2], short_id="bbbb"),  # Home — different group
        ]
        out = render.render(rows, render.PRETTY, group_by_list=True)
        plain = _strip_ansi(out)
        self.assertIn("aaaa", plain)
        self.assertIn("bbbb", plain)

    def test_short_id_prefix_comes_before_the_depth_indent(self):
        rows = [dict(_rows()[0], short_id="a3f1", depth=1, starred=False)]
        out = render.render(rows, render.PRETTY, group_by_list=False)
        plain = _strip_ansi(out)
        # depth=1 indents by 4 spaces (see test_indents_subtasks_by_depth);
        # the short id comes first, so the line does not start with the
        # raw 4-space indent the way an undecorated row does.
        self.assertFalse(plain.startswith("    "))
        self.assertIn("a3f1", plain.split("○")[0])

    def test_list_headers_get_a_background_band(self):
        out = render.render(_rows(), render.PRETTY, group_by_list=True)
        header_line = next(ln for ln in out.splitlines() if "Work" in ln)
        self.assertIn(render._BG_HEADER, header_line)

    def test_zebra_stripes_alternate_task_rows(self):
        # Two tasks in one group: first plain, second zebra.
        rows = [_rows()[0], _rows()[1]]  # both Work
        out = render.render(rows, render.PRETTY, group_by_list=True)
        task_lines = [
            ln for ln in out.splitlines()
            if "Ship CLI" in ln or "Review PR" in ln
        ]
        self.assertEqual(len(task_lines), 2)
        self.assertNotIn(render._BG_ZEBRA, task_lines[0])
        self.assertIn(render._BG_ZEBRA, task_lines[1])

    def test_plain_mode_never_emits_backgrounds(self):
        out = render.render(_rows(), render.PLAIN, group_by_list=True)
        self.assertNotIn("\x1b[48", out)

    def test_zebra_reopens_background_after_inner_reset(self):
        # A dim short id emits \x1b[0m mid-line; the zebra painter must
        # re-open the bg afterward or the stripe dies after the handle.
        rows = [
            dict(_rows()[0], short_id="a3f1"),
            dict(_rows()[1], short_id="b91c"),
        ]
        out = render.render(rows, render.PRETTY, group_by_list=False)
        zebra_line = next(ln for ln in out.splitlines() if "Review PR" in ln)
        # After the first reset that follows the dim handle, bg must return.
        self.assertGreater(zebra_line.count(render._BG_ZEBRA), 1)

    def test_plain_mode_shows_short_id_when_present(self):
        rows = [dict(_rows()[0], short_id="a3f1")]
        out = render.render(rows, render.PLAIN, group_by_list=False)
        self.assertEqual(out, "a3f1  [ ] Ship CLI  due 2026-08-05")

    def test_json_mode_carries_short_id_when_present(self):
        rows = [dict(_rows()[0], short_id="a3f1")]
        payload = json.loads(
            render.render(rows, render.JSON, group_by_list=False)
        )
        self.assertEqual(payload["tasks"][0]["short_id"], "a3f1")

    def test_json_mode_omits_short_id_when_absent(self):
        payload = json.loads(
            render.render(_rows()[:1], render.JSON, group_by_list=False)
        )
        self.assertNotIn("short_id", payload["tasks"][0])


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

    def test_raw_google_fields_survive_into_the_payload(self):
        payload = json.loads(
            render.render(_rows(), render.JSON, group_by_list=True)
        )
        task = payload["tasks"][0]
        self.assertEqual(task["id"], "t1")
        self.assertEqual(task["notes"], "ship it")

    def test_list_id_and_list_title_survive_into_the_payload(self):
        payload = json.loads(
            render.render(_rows(), render.JSON, group_by_list=True)
        )
        task = payload["tasks"][0]
        self.assertEqual(task["_list_id"], "L1")
        self.assertEqual(task["_list_title"], "Work")

    def test_raw_depth_and_list_title_are_not_in_the_json_item(self):
        payload = json.loads(
            render.render(_rows(), render.JSON, group_by_list=True)
        )
        task = payload["tasks"][0]
        self.assertNotIn("raw", task)
        self.assertNotIn("depth", task)
        self.assertNotIn("list_title", task)

    def test_does_not_mutate_the_input_rows(self):
        rows = _rows()
        original_raw = dict(rows[0]["raw"])
        render.render(rows, render.JSON, group_by_list=True)
        self.assertEqual(rows[0]["raw"], original_raw)
        self.assertEqual(rows[0]["raw"]["title"], "⭐Ship CLI")


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
