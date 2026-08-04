"""End-to-end tests for CLI dispatch.

run() is called as a plain function with captured streams — no subprocess,
no shell, no terminal. A temporary cache file stands in for ~/.gtask.
"""

import datetime
import io
import json
import os
import tempfile
import unittest

from tasks_tui import cli


def _cache_dict():
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    return {
        "last_sync": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "task_lists": [
            {"id": "L1", "title": "Work"},
            {"id": "L2", "title": "Home"},
        ],
        "tasks": {
            "L1": [
                {"id": "t1", "title": "⭐Ship CLI", "status": "needsAction",
                 "due": f"{today}T00:00:00.000Z"},
                {"id": "t2", "title": "Review PR", "status": "completed"},
                {"id": "t3", "title": "Old thing", "status": "needsAction",
                 "due": f"{yesterday}T00:00:00.000Z"},
            ],
            "L2": [
                {"id": "t4", "title": "⭐Buy milk", "status": "needsAction",
                 "notes": "semi-skimmed"},
            ],
        },
    }


class _CliCase(unittest.TestCase):
    """Base case: writes a temp cache and points the CLI at it."""

    def setUp(self):
        fd, self.cache_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(_cache_dict(), fh)
        os.environ["GTASK_CACHE_FILE"] = self.cache_path
        os.environ["NO_COLOR"] = "1"

    def tearDown(self):
        os.environ.pop("GTASK_CACHE_FILE", None)
        os.environ.pop("NO_COLOR", None)
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.run(argv, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()


class TestFav(_CliCase):
    def test_lists_starred_tasks_from_every_list(self):
        code, out, _ = self.run_cli(["fav"])
        self.assertEqual(code, 0)
        self.assertIn("Ship CLI", out)
        self.assertIn("Buy milk", out)

    def test_excludes_unstarred(self):
        _, out, _ = self.run_cli(["fav"])
        self.assertNotIn("Review PR", out)

    def test_restricts_to_one_list_with_dash_l(self):
        _, out, _ = self.run_cli(["fav", "-l", "Home"])
        self.assertIn("Buy milk", out)
        self.assertNotIn("Ship CLI", out)


class TestLists(_CliCase):
    def test_shows_every_list_with_counts(self):
        code, out, _ = self.run_cli(["lists"])
        self.assertEqual(code, 0)
        self.assertIn("Work", out)
        self.assertIn("Home", out)

    def test_counts_exclude_completed_from_undone(self):
        _, out, _ = self.run_cli(["lists"])
        work = [ln for ln in out.splitlines() if ln.startswith("Work")][0]
        self.assertIn("2/3", work)


class TestListVerb(_CliCase):
    def test_shows_tasks_in_the_named_list(self):
        code, out, _ = self.run_cli(["list", "Work"])
        self.assertEqual(code, 0)
        self.assertIn("Ship CLI", out)

    def test_hides_completed_by_default(self):
        _, out, _ = self.run_cli(["list", "Work"])
        self.assertNotIn("Review PR", out)

    def test_dash_a_includes_completed(self):
        _, out, _ = self.run_cli(["list", "Work", "-a"])
        self.assertIn("Review PR", out)

    def test_partial_name_resolves(self):
        code, out, _ = self.run_cli(["list", "Wo"])
        self.assertEqual(code, 0)
        self.assertIn("Ship CLI", out)

    def test_unknown_name_exits_2_with_stderr(self):
        code, out, err = self.run_cli(["list", "zzz"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no list matches", err)


class TestDateVerbs(_CliCase):
    def test_today_shows_only_tasks_due_today(self):
        code, out, _ = self.run_cli(["today"])
        self.assertEqual(code, 0)
        self.assertIn("Ship CLI", out)
        self.assertNotIn("Old thing", out)

    def test_overdue_shows_only_past_due(self):
        _, out, _ = self.run_cli(["overdue"])
        self.assertIn("Old thing", out)
        self.assertNotIn("Ship CLI", out)


class TestSearch(_CliCase):
    def test_matches_title(self):
        code, out, _ = self.run_cli(["search", "milk"])
        self.assertEqual(code, 0)
        self.assertIn("Buy milk", out)

    def test_matches_notes(self):
        _, out, _ = self.run_cli(["search", "skimmed"])
        self.assertIn("Buy milk", out)

    def test_no_results_still_exits_zero(self):
        code, out, _ = self.run_cli(["search", "zzz"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


class TestStalenessFooter(_CliCase):
    def test_footer_goes_to_stderr_not_stdout(self):
        _, out, err = self.run_cli(["fav"])
        self.assertIn("synced", err)
        self.assertNotIn("synced", out)

    def test_quiet_suppresses_the_footer(self):
        _, _, err = self.run_cli(["fav", "-q"])
        self.assertEqual(err, "")

    def test_json_puts_it_in_the_payload_and_not_stderr(self):
        _, out, err = self.run_cli(["fav", "--json"])
        payload = json.loads(out)
        self.assertIn("stale_seconds", payload)
        self.assertEqual(err, "")


class TestMissingCache(unittest.TestCase):
    def test_absent_cache_exits_1_with_guidance(self):
        os.environ["GTASK_CACHE_FILE"] = "/nonexistent/local_tasks.json"
        try:
            out, err = io.StringIO(), io.StringIO()
            code = cli.run(["fav"], stdout=out, stderr=err)
            self.assertEqual(code, 1)
            self.assertIn("no local cache", err.getvalue())
        finally:
            os.environ.pop("GTASK_CACHE_FILE", None)


if __name__ == "__main__":
    unittest.main()
