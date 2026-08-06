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


class _TTYStringIO(io.StringIO):
    """A stdout stand-in that reports itself as a terminal.

    Needed to exercise pretty-mode rendering (indentation, colour), since a
    plain io.StringIO().isatty() is always False and pick_mode() would
    downgrade to plain.
    """

    def isatty(self):
        return True


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

        fd, self.short_ids_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.short_ids_path)  # start absent
        os.environ["GTASK_SHORT_IDS_FILE"] = self.short_ids_path

        os.environ["NO_COLOR"] = "1"

    def tearDown(self):
        os.environ.pop("GTASK_CACHE_FILE", None)
        os.environ.pop("GTASK_SHORT_IDS_FILE", None)
        os.environ.pop("NO_COLOR", None)
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)
        if os.path.exists(self.short_ids_path):
            os.remove(self.short_ids_path)

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


class TestUnknownVerb(_CliCase):
    def test_typo_exits_2_instead_of_falling_through_to_the_tui(self):
        # argparse writes its "invalid choice" error to the real sys.stderr,
        # not the injected stream, so only the return code is asserted here.
        code, _, _ = self.run_cli(["favs"])
        self.assertEqual(code, 2)


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


class TestMalformedCache(unittest.TestCase):
    """A cache file that parses as JSON but is not an object (M-traceback)."""

    def setUp(self):
        fd, self.cache_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump([], fh)  # valid JSON, not a dict
        os.environ["GTASK_CACHE_FILE"] = self.cache_path

    def tearDown(self):
        os.environ.pop("GTASK_CACHE_FILE", None)
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)

    def test_non_dict_cache_exits_1_with_message_not_a_traceback(self):
        out, err = io.StringIO(), io.StringIO()
        code = cli.run(["fav"], stdout=out, stderr=err)
        self.assertEqual(code, 1)
        self.assertIn(self.cache_path, err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(out.getvalue(), "")


class TestJsonPayload(_CliCase):
    """--json must carry raw Google fields, not just the six row keys (I1)."""

    def test_fav_payload_carries_id_and_notes(self):
        _, out, _ = self.run_cli(["fav", "--json"])
        payload = json.loads(out)
        by_title = {t["title"]: t for t in payload["tasks"]}
        self.assertEqual(by_title["Ship CLI"]["id"], "t1")
        self.assertEqual(by_title["Buy milk"]["notes"], "semi-skimmed")

    def test_fav_payload_title_has_no_star_marker_but_starred_is_true(self):
        _, out, _ = self.run_cli(["fav", "--json"])
        payload = json.loads(out)
        by_title = {t["title"]: t for t in payload["tasks"]}
        self.assertNotIn("⭐", by_title["Ship CLI"]["title"])
        self.assertTrue(by_title["Ship CLI"]["starred"])

    def test_fav_payload_due_is_iso_string_or_null(self):
        _, out, _ = self.run_cli(["fav", "--json"])
        payload = json.loads(out)
        by_title = {t["title"]: t for t in payload["tasks"]}
        self.assertEqual(
            by_title["Ship CLI"]["due"], datetime.date.today().isoformat()
        )
        self.assertIsNone(by_title["Buy milk"]["due"])

    def test_fav_payload_carries_list_id_and_list_title(self):
        _, out, _ = self.run_cli(["fav", "--json"])
        payload = json.loads(out)
        for task in payload["tasks"]:
            self.assertIn("_list_id", task)
            self.assertIn("_list_title", task)

    def test_fav_payload_omits_raw_depth_and_list_title_keys(self):
        _, out, _ = self.run_cli(["fav", "--json"])
        payload = json.loads(out)
        for task in payload["tasks"]:
            self.assertNotIn("raw", task)
            self.assertNotIn("depth", task)
            self.assertNotIn("list_title", task)

    def test_list_verb_payload_also_carries_list_id_and_title(self):
        _, out, _ = self.run_cli(["list", "Work", "--json"])
        payload = json.loads(out)
        self.assertTrue(payload["tasks"])
        for task in payload["tasks"]:
            self.assertEqual(task["_list_id"], "L1")
            self.assertEqual(task["_list_title"], "Work")


class TestListVerbSubtasks(unittest.TestCase):
    """`list <name>` must render subtasks indented under their parent, in
    parent-then-children order, not raw cache order (I2)."""

    def _cache(self):
        return {
            "last_sync": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "task_lists": [{"id": "L1", "title": "Work"}],
            "tasks": {
                "L1": [
                    # Raw cache order deliberately interleaves an unrelated
                    # top-level task between a parent and its child, matching
                    # the bug reproduction in the review: a naive flat render
                    # would print Parent A, Zebra top, Child of A in that
                    # order with no indentation.
                    {"id": "p1", "title": "Parent A", "status": "needsAction"},
                    {"id": "z1", "title": "Zebra top", "status": "needsAction"},
                    {"id": "c1", "title": "Child of A", "status": "needsAction",
                     "parent": "p1"},
                    # A completed parent: its uncompleted child must not be
                    # orphaned under a heading that got filtered out.
                    {"id": "p2", "title": "Parent B", "status": "completed"},
                    {"id": "c2", "title": "Child of B", "status": "needsAction",
                     "parent": "p2"},
                    # An uncompleted parent with a completed child: the child
                    # is filtered on its own merits, independent of the
                    # parent surviving.
                    {"id": "p3", "title": "Parent C", "status": "needsAction"},
                    {"id": "c3", "title": "Child of C done",
                     "status": "completed", "parent": "p3"},
                ],
            },
        }

    def setUp(self):
        fd, self.cache_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(self._cache(), fh)
        os.environ["GTASK_CACHE_FILE"] = self.cache_path

        fd, self.short_ids_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.short_ids_path)
        os.environ["GTASK_SHORT_IDS_FILE"] = self.short_ids_path

        os.environ.pop("NO_COLOR", None)

    def tearDown(self):
        os.environ.pop("GTASK_CACHE_FILE", None)
        os.environ.pop("GTASK_SHORT_IDS_FILE", None)
        os.environ.pop("NO_COLOR", None)
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)
        if os.path.exists(self.short_ids_path):
            os.remove(self.short_ids_path)

    def run_cli(self, argv):
        out, err = _TTYStringIO(), io.StringIO()
        code = cli.run(argv, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_child_follows_parent_immediately_and_is_indented(self):
        _, out, _ = self.run_cli(["list", "Work", "-a"])
        lines = out.splitlines()
        parent_idx = next(i for i, ln in enumerate(lines) if "Parent A" in ln)
        child_idx = next(i for i, ln in enumerate(lines) if "Child of A" in ln)
        self.assertEqual(child_idx, parent_idx + 1)
        # The number prefix comes before the depth indent (Task 3), so
        # indentation now shows up as extra space *after* the number rather
        # than at the start of the line. str.split(None, 1) would collapse
        # that indent away along with the number (both are just runs of
        # space characters with nothing to tell them apart), so instead
        # strip only the leading digits and compare how many spaces remain
        # before the glyph — the child's indent must be exactly one level
        # (two spaces) deeper than the parent's.
        def leading_spaces(line):
            body = line.lstrip("0123456789")
            return len(body) - len(body.lstrip(" "))

        parent_spaces = leading_spaces(lines[parent_idx])
        child_spaces = leading_spaces(lines[child_idx])
        self.assertEqual(child_spaces, parent_spaces + 2)

    def test_order_is_parent_then_child_not_raw_cache_order(self):
        _, out, _ = self.run_cli(["list", "Work", "-a"])
        titles = [
            next(t for t in ("Parent A", "Zebra top", "Child of A") if t in ln)
            for ln in out.splitlines()
            if any(t in ln for t in ("Parent A", "Zebra top", "Child of A"))
        ]
        self.assertEqual(titles, ["Parent A", "Child of A", "Zebra top"])

    def test_completed_parent_hides_its_uncompleted_child_by_default(self):
        _, out, _ = self.run_cli(["list", "Work"])
        self.assertNotIn("Parent B", out)
        self.assertNotIn("Child of B", out)

    def test_dash_a_shows_completed_parent_and_its_child(self):
        _, out, _ = self.run_cli(["list", "Work", "-a"])
        self.assertIn("Parent B", out)
        self.assertIn("Child of B", out)

    def test_completed_child_is_hidden_even_though_its_parent_survives(self):
        _, out, _ = self.run_cli(["list", "Work"])
        self.assertIn("Parent C", out)
        self.assertNotIn("Child of C done", out)

    def test_dash_a_shows_the_completed_child_too(self):
        _, out, _ = self.run_cli(["list", "Work", "-a"])
        self.assertIn("Parent C", out)
        self.assertIn("Child of C done", out)


class TestShortIdMapping(_CliCase):
    """Every listing verb writes number -> (list_id, task_id) after
    rendering, matching what the pretty-mode output shows the user."""

    def _read_mapping(self):
        with open(self.short_ids_path) as f:
            return json.load(f)

    def test_fav_writes_a_mapping_for_every_printed_task(self):
        self.run_cli(["fav"])
        mapping = self._read_mapping()
        # _cache_dict()'s starred tasks are t1 (Work) and t4 (Home); fav
        # groups and sorts by list_title, so Home (t4) sorts before Work
        # (t1) alphabetically.
        self.assertEqual(mapping["1"], {"list_id": "L2", "task_id": "t4"})
        self.assertEqual(mapping["2"], {"list_id": "L1", "task_id": "t1"})

    def test_list_verb_writes_a_mapping_in_parent_child_order(self):
        self.run_cli(["list", "Work"])
        mapping = self._read_mapping()
        self.assertEqual(mapping["1"], {"list_id": "L1", "task_id": "t1"})
        self.assertEqual(mapping["2"], {"list_id": "L1", "task_id": "t3"})

    def test_lists_verb_does_not_write_a_mapping(self):
        self.run_cli(["fav"])  # seed a mapping first
        os.remove(self.short_ids_path)
        self.run_cli(["lists"])
        self.assertFalse(os.path.exists(self.short_ids_path))

    def test_a_second_listing_overwrites_the_first_mapping(self):
        self.run_cli(["fav"])
        first = self._read_mapping()
        self.assertIn("2", first)
        self.run_cli(["list", "Home"])
        second = self._read_mapping()
        self.assertNotIn("2", second)  # Home has exactly one task

    def test_json_mode_still_writes_the_mapping(self):
        self.run_cli(["fav", "--json"])
        mapping = self._read_mapping()
        self.assertIn("1", mapping)

    def test_empty_result_writes_an_empty_mapping(self):
        self.run_cli(["search", "zzz"])
        self.assertEqual(self._read_mapping(), {})

    def test_pretty_output_shows_the_same_numbers_as_the_mapping(self):
        # _CliCase.setUp sets NO_COLOR=1, which forces plain mode regardless
        # of isatty() (render.pick_mode: `if not is_tty or no_color: PLAIN`)
        # — and plain mode never shows numbers. Unset it here so a TTY
        # stdout actually gets pretty mode, the only mode this test can
        # observe numbering in.
        os.environ.pop("NO_COLOR", None)
        out_stream = _TTYStringIO()
        err_stream = io.StringIO()
        cli.run(["fav"], stdout=out_stream, stderr=err_stream)
        out = out_stream.getvalue()
        mapping = self._read_mapping()
        lines_with_1 = [ln for ln in out.splitlines() if ln.lstrip().startswith("1")]
        self.assertTrue(lines_with_1)
        self.assertIn("Buy milk", lines_with_1[0])  # mapping["1"] is t4
        self.assertEqual(mapping["1"]["task_id"], "t4")


class _FakeGoogleReq:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._response


class _FakeGoogleTasks:
    """Mimics service.tasks() for sync_to_google(): list() + patch()."""

    def __init__(self, google_state, fail_patch=False):
        self._state = google_state  # {list_id: [task_dict, ...]}
        self.fail_patch = fail_patch
        self.patch_calls = []

    def list(self, tasklist, showHidden=True):
        return _FakeGoogleReq({"items": self._state.get(tasklist, [])})

    def patch(self, tasklist, task, body):
        self.patch_calls.append((tasklist, task, body))
        if self.fail_patch:
            return _FakeGoogleReq(error=RuntimeError("network down"))
        return _FakeGoogleReq({})


class _FakeGoogleTasklists:
    """Mimics service.tasklists() for sync_to_google()'s list-rename check,
    which runs unconditionally (before any per-task syncing) whenever the
    service is dirty. None of these fixtures rename a list, so an empty
    items list lets sync_to_google() fall straight through to tasks()."""

    def list(self):
        return _FakeGoogleReq({"items": []})


class _FakeGoogleService:
    def __init__(self, google_state, fail_patch=False):
        self._tasks = _FakeGoogleTasks(google_state, fail_patch=fail_patch)
        self._tasklists = _FakeGoogleTasklists()

    def tasks(self):
        return self._tasks

    def tasklists(self):
        return self._tasklists


class _DoneCase(unittest.TestCase):
    """Base case for `done`: a temp cache/short-ids pair, plus a
    TaskService whose __init__ is monkeypatched so `TaskService()` inside
    cli.py's _verb_done never touches real credentials or the network.
    """

    def setUp(self):
        fd, self.cache_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.cache_path)
        os.environ["GTASK_CACHE_FILE"] = self.cache_path

        fd, self.short_ids_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.short_ids_path)
        os.environ["GTASK_SHORT_IDS_FILE"] = self.short_ids_path

        self.addCleanup(os.environ.pop, "GTASK_CACHE_FILE", None)
        self.addCleanup(os.environ.pop, "GTASK_SHORT_IDS_FILE", None)
        self.addCleanup(self._remove_if_exists, self.cache_path)
        self.addCleanup(self._remove_if_exists, self.short_ids_path)

    def _remove_if_exists(self, path):
        if os.path.exists(path):
            os.remove(path)

    def _install_fake_task_service(self, data, google_service):
        import tasks_tui.task_service as ts_module

        def fake_init(instance):
            instance.data = data
            instance.dirty = False
            instance.service = google_service
            instance.initial_sync_completed = True
            instance.active_list_id = None

        original_init = ts_module.TaskService.__init__
        ts_module.TaskService.__init__ = fake_init
        self.addCleanup(setattr, ts_module.TaskService, "__init__", original_init)

    def _seed_mapping(self, mapping):
        import tasks_tui.shortids as shortids_module
        shortids_module.write(mapping)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.run(argv, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()


class TestDoneHappyPath(_DoneCase):
    def test_marks_done_and_syncs(self):
        data = {
            "task_lists": [{"id": "L1", "title": "Work"}],
            "tasks": {"L1": [
                {"id": "t1", "title": "Ship CLI", "status": "needsAction"},
            ]},
        }
        google = _FakeGoogleService(
            {"L1": [{"id": "t1", "title": "Ship CLI", "status": "needsAction"}]}
        )
        self._install_fake_task_service(data, google)
        self._seed_mapping({1: {"list_id": "L1", "task_id": "t1"}})

        code, out, err = self.run_cli(["done", "1"])

        self.assertEqual(code, 0)
        self.assertIn('marked "Ship CLI" done', out)
        self.assertIn("synced", out)
        self.assertEqual(data["tasks"]["L1"][0]["status"], "completed")
        self.assertEqual(len(google.tasks().patch_calls), 1)

    def test_cascades_to_subtasks_like_the_tui_does(self):
        data = {
            "task_lists": [{"id": "L1", "title": "Work"}],
            "tasks": {"L1": [
                {"id": "p1", "title": "Parent", "status": "needsAction"},
                {"id": "c1", "title": "Child", "status": "needsAction",
                 "parent": "p1"},
            ]},
        }
        google = _FakeGoogleService({"L1": [
            {"id": "p1", "title": "Parent", "status": "needsAction"},
            {"id": "c1", "title": "Child", "status": "needsAction",
             "parent": "p1"},
        ]})
        self._install_fake_task_service(data, google)
        self._seed_mapping({1: {"list_id": "L1", "task_id": "p1"}})

        code, _, _ = self.run_cli(["done", "1"])

        self.assertEqual(code, 0)
        by_id = {t["id"]: t for t in data["tasks"]["L1"]}
        self.assertEqual(by_id["p1"]["status"], "completed")
        self.assertEqual(by_id["c1"]["status"], "completed")


class TestDoneAlreadyDone(_DoneCase):
    def test_no_op_does_not_toggle_or_sync(self):
        data = {
            "task_lists": [{"id": "L1", "title": "Work"}],
            "tasks": {"L1": [
                {"id": "t1", "title": "Ship CLI", "status": "completed"},
            ]},
        }
        google = _FakeGoogleService({"L1": []})
        self._install_fake_task_service(data, google)
        self._seed_mapping({1: {"list_id": "L1", "task_id": "t1"}})

        code, out, _ = self.run_cli(["done", "1"])

        self.assertEqual(code, 0)
        self.assertIn('"Ship CLI" is already done', out)
        self.assertEqual(data["tasks"]["L1"][0]["status"], "completed")
        self.assertEqual(len(google.tasks().patch_calls), 0)


class TestDoneMissingMapping(_DoneCase):
    def test_no_mapping_file_exits_2(self):
        code, out, err = self.run_cli(["done", "1"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no task numbered 1", err)

    def test_number_not_in_mapping_exits_2(self):
        self._seed_mapping({1: {"list_id": "L1", "task_id": "t1"}})
        code, out, err = self.run_cli(["done", "9"])
        self.assertEqual(code, 2)
        self.assertIn("no task numbered 9", err)


class TestDoneStaleMapping(_DoneCase):
    def test_task_deleted_since_the_listing_exits_2(self):
        data = {"task_lists": [{"id": "L1", "title": "Work"}], "tasks": {"L1": []}}
        google = _FakeGoogleService({"L1": []})
        self._install_fake_task_service(data, google)
        self._seed_mapping({1: {"list_id": "L1", "task_id": "gone"}})

        code, out, err = self.run_cli(["done", "1"])

        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no longer exists", err)


class TestDoneSyncFailure(_DoneCase):
    def test_local_toggle_persisted_to_disk_when_sync_fails(self):
        data = {
            "task_lists": [{"id": "L1", "title": "Work"}],
            "tasks": {"L1": [
                {"id": "t1", "title": "Ship CLI", "status": "needsAction"},
            ]},
        }
        google = _FakeGoogleService(
            {"L1": [{"id": "t1", "title": "Ship CLI", "status": "needsAction"}]},
            fail_patch=True,
        )
        self._install_fake_task_service(data, google)
        self._seed_mapping({1: {"list_id": "L1", "task_id": "t1"}})

        code, out, err = self.run_cli(["done", "1"])

        self.assertEqual(code, 1)
        self.assertIn('marked "Ship CLI" done locally', out)
        self.assertIn("could not reach Google", err)
        self.assertIn("it will push next time you open the TUI", err)
        # sync_to_google() only calls save_local_data() as its very last
        # line, never reached when the push fails — so the toggle must be
        # persisted independently, or it would exist only in this
        # process's memory and be lost when the process exits. Re-read
        # the on-disk cache file (not the in-memory `data` dict, which
        # would look "correct" here regardless of whether anything was
        # actually written) to prove it really was saved.
        with open(self.cache_path) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["tasks"]["L1"][0]["status"], "completed")

    def test_local_save_also_failing_does_not_claim_success(self):
        # local_storage.save_data() swallows IOError and historically
        # returned None either way, so _verb_done's failure branch could
        # not tell a persisted toggle from a lost one and always printed
        # "done locally". Monkeypatching save_data() to report failure
        # (simpler and more reliable across CI than relying on real
        # filesystem permission failures) exercises that branch directly.
        data = {
            "task_lists": [{"id": "L1", "title": "Work"}],
            "tasks": {"L1": [
                {"id": "t1", "title": "Ship CLI", "status": "needsAction"},
            ]},
        }
        google = _FakeGoogleService(
            {"L1": [{"id": "t1", "title": "Ship CLI", "status": "needsAction"}]},
            fail_patch=True,
        )
        self._install_fake_task_service(data, google)
        self._seed_mapping({1: {"list_id": "L1", "task_id": "t1"}})

        import tasks_tui.local_storage as local_storage_module

        original_save_data = local_storage_module.save_data
        local_storage_module.save_data = lambda _data: False
        self.addCleanup(
            setattr, local_storage_module, "save_data", original_save_data
        )

        code, out, err = self.run_cli(["done", "1"])

        self.assertEqual(code, 1)
        self.assertNotIn("done locally", out)
        self.assertNotIn("it will push next time you open the TUI", err)
        self.assertIn("could not save locally", err)


class TestDoneConstructionFailure(_DoneCase):
    def test_task_service_construction_failure_exits_1(self):
        import tasks_tui.task_service as ts_module

        def failing_init(instance):
            raise RuntimeError("no credentials")

        original_init = ts_module.TaskService.__init__
        ts_module.TaskService.__init__ = failing_init
        self.addCleanup(setattr, ts_module.TaskService, "__init__", original_init)

        self._seed_mapping({1: {"list_id": "L1", "task_id": "t1"}})

        code, out, err = self.run_cli(["done", "1"])

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("could not connect", err)


class TestDoneArgparse(_DoneCase):
    def test_non_integer_argument_exits_2(self):
        # argparse's own type=int error goes to the real stderr, not the
        # injected stream — only the return code is asserted, same pattern
        # already used for the typo'd-verb case.
        code, _, _ = self.run_cli(["done", "abc"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
