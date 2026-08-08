# `done` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tasks-tui done <N>`, completing a task addressed by the short
ephemeral number a listing verb (`fav`, `list`, `today`, `overdue`, `search`)
just printed next to it, then pushing the change to Google before the
command exits.

**Architecture:** A new pure-I/O module `shortids.py` writes and reads a
number → `(list_id, task_id)` mapping file, overwritten by every listing
verb after it renders. `render.py` gains an optional, opt-in number prefix
in pretty mode only — a row is numbered if and only if it already carries a
`number` key, so no existing test or output format changes unless `cli.py`
explicitly assigns one. `cli.py` assigns numbers and writes the mapping
right after building the final row order for each listing verb, then a new
`done` verb reads the mapping, toggles the task via the existing
`TaskService.toggle_task_status`, and pushes with `sync_to_google` —
mirroring what the TUI already does on every quit, idle timeout, or `w`.

**Tech Stack:** Python 3.13, standard library `argparse` + `unittest` +
`json`. No new dependencies.

## Global Constraints

- **Test runner is `unittest`, not pytest.** pytest is not installed. Run
  `.venv/bin/python -m unittest discover tests -v`.
- **All existing tests must keep passing** — currently 126 across
  `test_history.py`, `test_queries.py`, `test_freshness.py`,
  `test_render.py`, `test_cli.py`, `test_sync_animation.py`.
- **`unicurses` must never be imported on the CLI path.** `main.py` imports
  it at module scope, which initializes terminal state. `cli.py` already
  imports `TaskService` lazily, inside `_verb_sync`, for exactly this
  reason — the new `_verb_done` follows the same pattern.
- **The number prefix appears in pretty mode only** (ratified during
  design review — see spec addendum below). Plain and JSON output are
  byte-identical to what they produce today; no existing test in
  `test_render.py` may need to change because of this feature.
- **`done` pushes to Google before the command exits.** It does not defer
  to a later `sync` the way an idle TUI session would — a one-shot CLI
  process has no idle time to defer through. On a sync failure, `done`
  explicitly calls `save_local_data()` so the toggle survives to disk (see
  the second spec addendum below — the original design assumed the toggle
  would survive in memory until a later retry, which is false for a
  process that has already exited), and the command exits 1.
- **Exit codes:** 0 success (marked and synced, or already done); 1 runtime
  error (`TaskService()` construction failed, or sync failed after a
  successful local toggle); 2 usage error (no mapping, unresolvable number,
  or the mapped task no longer exists).
- **Spec:** `docs/superpowers/specs/2026-08-05-done-command-design.md`.

### Spec addendum (found and ratified during planning)

The approved spec's example output shows a number prefix
(`1  ○ Ship CLI mode`) but its Architecture section never lists a
`render.py` change — an oversight caught during planning. Ratified during
planning, before any code was written: **the number prefix appears in
pretty mode only.** Plain mode (piped output, scripts) is unchanged, since
it is the format anything currently parsing this CLI's output depends on.
JSON is unaffected either way — it already carries the real, permanent
`id` (from the earlier `--json` fix), a better identifier for scripting
than an ephemeral number.

**Second addendum (found and ratified during Task 5's review, before Task
5 was marked complete):** the approved spec's failure-path design said a
failed sync's toggle "survives into the next successful sync" and
suggested `run 'tasks-tui sync' to retry`. Both are wrong for a one-shot
CLI process. `save_local_data()` runs only as the last line of
`sync_to_google()` (`task_service.py:606`), never reached on failure, so
the toggle would vanish the moment `done` exits unless saved explicitly —
and `sync` calls `sync_from_google()` (a pull), so following that advice
would overwrite the very change it claimed to help retry. Ratified fix,
minimal scope: `done`'s failure branch calls `service.save_local_data()`
itself, and the message drops the specific retry command in favor of
`it will push next time you open the TUI` — the TUI's existing
flush-on-quit/idle/`w` is, today, the only thing that pushes. Expanding
`sync` into a push-then-pull verb was considered and explicitly deferred
as a larger, separate change to already-shipped behavior. Task 5's brief
and tests below already reflect this fix.

**Third addendum (found and ratified during the final whole-branch
review, after all six tasks were individually marked complete):**
`shortids.write()` was called unconditionally after every successful
render in Task 4, but numbers only ever print in pretty mode (first
addendum, above). A piped, `--json`, or `NO_COLOR` listing therefore
overwrote the mapping with entries for numbers the user never saw,
silently repointing a still-valid `done N` at the wrong task. Ratified
fix: `cli.py` writes the mapping only when the render mode was pretty —
`if mode == render.PRETTY: shortids.write(mapping)` — leaving the mapping
untouched by any listing whose numbers were never shown. The same review
pass also fixed two implementation gaps that needed no design ruling: (a)
`_verb_done`'s failure branch could itself report a false "done locally"
if the local disk write also failed, since `save_data()` swallows
`IOError` — fixed by checking the save actually reached disk before
printing success; (b) `shortids.write()` had no error handling at all, so
an unwritable mapping file crashed a previously-safe read-only listing
verb with a raw traceback — fixed by catching the write failure and
reporting it the way every other error path in `cli.py` already does. Task
4's and Task 5's code below already reflect all three fixes.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `tasks_tui/local_storage.py` | Modify | `load_data()`/`save_data()` honor `cache_path()`; add `short_ids_path()` |
| `tasks_tui/shortids.py` | Create | Pure I/O: write/read the number → `(list_id, task_id)` mapping |
| `tasks_tui/render.py` | Modify | Optional row-number prefix, pretty mode only |
| `tasks_tui/cli.py` | Modify | Assign numbers + write mapping in listing verbs; new `done` verb |
| `tests/test_local_storage.py` | Create | Task 1 |
| `tests/test_shortids.py` | Create | Task 2 |
| `tests/test_render.py` | Modify (additions only) | Task 3 |
| `tests/test_cli.py` | Modify | Tasks 4–5 |
| `README.md` | Modify | Task 6 |

---

## Task 1: `local_storage.py` — honor `cache_path()`, add `short_ids_path()`

**Files:**
- Modify: `tasks_tui/local_storage.py`
- Test: `tests/test_local_storage.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `local_storage.load_data()` — unchanged signature, now reads from
    `cache_path()` instead of the hardcoded `STORAGE_FILE`
  - `local_storage.save_data(data)` — unchanged signature, now writes to
    `cache_path()`
  - `local_storage.SHORT_IDS_FILE: str`
  - `local_storage.short_ids_path() -> str`

**Why this task exists:** `cli.py`'s read-only verbs already use
`local_storage.cache_path()` to let tests point at a fixture instead of the
real `~/.gtask/local_tasks.json`. `load_data()`/`save_data()` — called by
`TaskService.__init__` and `save_local_data()` — still hardcode
`STORAGE_FILE` directly. `done` and `sync` both go through
`TaskService.sync_to_google()`, which ends with `save_local_data()`, so
without this fix, a `done` test would silently write to the developer's
real cache file. For a real user, `cache_path()` returns exactly
`STORAGE_FILE` when `GTASK_CACHE_FILE` is unset, so this is not a behavior
change for normal use — only test/CI environments that set the override see
different behavior.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_local_storage.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_local_storage -v`
Expected: FAIL — `TestLoadDataHonorsOverride`/`TestSaveDataHonorsOverride`
fail because `load_data`/`save_data` still read/write the real
`STORAGE_FILE`, not the override; `TestShortIdsPath` fails with
`AttributeError: module 'tasks_tui.local_storage' has no attribute
'short_ids_path'`.

- [ ] **Step 3: Write the implementation**

In `tasks_tui/local_storage.py`, add below `CONFIG_FILE`:

```python
SHORT_IDS_FILE = os.path.join(GTASK_DIR, "last_ids.json")


def short_ids_path():
    """Path to the done-command short-id mapping. GTASK_SHORT_IDS_FILE
    overrides it, the same pattern cache_path()/GTASK_CACHE_FILE already
    uses, so tests never touch the real ~/.gtask."""
    return os.environ.get("GTASK_SHORT_IDS_FILE", SHORT_IDS_FILE)
```

Replace `load_data()`:

```python
def load_data():
    """Loads task data from the local JSON storage file."""
    _ensure_dir_exists()
    path = cache_path()
    if not os.path.exists(path):
        return {"task_lists": [], "tasks": {}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"task_lists": [], "tasks": {}}
```

Replace `save_data()`:

```python
def save_data(data):
    """Saves task data to the local JSON storage file."""
    _ensure_dir_exists()
    try:
        with open(cache_path(), "w") as f:
            json.dump(data, f, indent=4)
    except IOError:
        # Handle cases where the file cannot be written
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_local_storage -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Verify nothing regressed**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: PASS, 126 + 6 = 132 tests. (`test_history.py`'s
`TaskService.__new__`-based tests bypass `__init__` entirely, so they never
call `load_data`/`save_data` and are unaffected.)

- [ ] **Step 6: Commit**

```bash
git add tasks_tui/local_storage.py tests/test_local_storage.py
git commit -m "fix: honor GTASK_CACHE_FILE in load_data/save_data, add short_ids_path"
```

---

## Task 2: `shortids.py` — mapping file I/O

**Files:**
- Create: `tasks_tui/shortids.py`
- Test: `tests/test_shortids.py`

**Interfaces:**
- Consumes: `local_storage.short_ids_path()` (Task 1)
- Produces:
  - `shortids.write(mapping: dict[int, dict]) -> None`
  - `shortids.read() -> dict[str, dict] | None` — `None` if the file is
    missing, is not valid JSON, or parses to something other than a JSON
    object

- [ ] **Step 1: Write the failing tests**

Create `tests/test_shortids.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_shortids -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tasks_tui.shortids'`

- [ ] **Step 3: Write the implementation**

Create `tasks_tui/shortids.py`:

```python
"""Ephemeral number -> (list_id, task_id) mapping for `tasks-tui done <N>`.

Every listing verb (fav, list, today, overdue, search) overwrites this file
after it finishes rendering, so a number always means "row N of the most
recent listing" and never anything older. Pure I/O — no cache logic, no
network, no credentials.
"""

import json
import os

from . import local_storage


def write(mapping):
    """Overwrites the mapping file. `mapping` is {int: {"list_id": str,
    "task_id": str}}; json.dump stringifies the int keys automatically, so
    read() always sees string keys back."""
    path = local_storage.short_ids_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2)


def read():
    """Returns the mapping (string keys) or None if the file is missing,
    is not valid JSON, or is not a JSON object."""
    path = local_storage.short_ids_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_shortids -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Verify nothing regressed**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: PASS, 132 + 7 = 139 tests

- [ ] **Step 6: Commit**

```bash
git add tasks_tui/shortids.py tests/test_shortids.py
git commit -m "feat: add the done-command short-id mapping file"
```

---

## Task 3: `render.py` — optional row-number prefix, pretty mode only

**Files:**
- Modify: `tasks_tui/render.py`
- Test: `tests/test_render.py` (additions only — no existing test changes)

**Interfaces:**
- Consumes: nothing new from earlier tasks
- Produces: `_render_pretty` reads an optional `row["number"]` (int or
  absent) and, when present, prepends it right-aligned before the row's
  existing indent/glyph. `render()`'s public signature is unchanged.

**Why existing tests are untouched:** every current fixture row in
`test_render.py`'s `_rows()` has no `"number"` key. The new code path is
gated on `row.get("number") is not None` — absent means "print exactly as
today." Numbering only turns on when a caller (Task 4's `cli.py`)
deliberately assigns it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`, inside the existing `class TestPretty`
(above `class TestJson`):

```python
    def test_numbers_are_not_printed_when_absent_from_the_row(self):
        out = render.render(_rows(), render.PRETTY, group_by_list=True)
        self.assertNotIn("1  ", out)

    def test_prints_the_row_number_when_present(self):
        rows = [dict(_rows()[0], number=1)]
        out = render.render(rows, render.PRETTY, group_by_list=False)
        self.assertTrue(out.lstrip().startswith("1"))

    def test_numbers_run_sequentially_across_group_headers(self):
        rows = [
            dict(_rows()[0], number=1),  # Work
            dict(_rows()[2], number=2),  # Home — different group
        ]
        out = render.render(rows, render.PRETTY, group_by_list=True)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        numbered = [ln for ln in lines if ln.lstrip()[:1].isdigit()]
        self.assertEqual(len(numbered), 2)
        self.assertTrue(numbered[0].lstrip().startswith("1"))
        self.assertTrue(numbered[1].lstrip().startswith("2"))

    def test_number_prefix_comes_before_the_depth_indent(self):
        rows = [dict(_rows()[0], number=1, depth=1, starred=False)]
        out = render.render(rows, render.PRETTY, group_by_list=False)
        # depth=1 indents by 4 spaces (see test_indents_subtasks_by_depth);
        # the number prefix comes first, so the line does not start with
        # the raw 4-space indent the way an unnumbered row does.
        self.assertFalse(out.startswith("    "))
        self.assertIn("1", out.split("○")[0])

    def test_plain_mode_never_shows_a_number_even_if_present(self):
        rows = [dict(_rows()[0], number=1)]
        out = render.render(rows, render.PLAIN, group_by_list=False)
        self.assertEqual(out, "[ ] Ship CLI  due 2026-08-05")

    def test_json_mode_never_shows_a_number_even_if_present(self):
        rows = [dict(_rows()[0], number=1)]
        payload = json.loads(
            render.render(rows, render.JSON, group_by_list=False)
        )
        self.assertNotIn("number", payload["tasks"][0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_render.TestPretty -v`
Expected: FAIL — the four new pretty-mode assertions fail because no number
is ever printed yet. (The plain/json tests in this batch already pass,
since those code paths are untouched — that's expected, not a problem;
they exist to lock the "never shows a number" behavior in *before* the
implementation step, so a future regression there is caught immediately.)

- [ ] **Step 3: Write the implementation**

In `tasks_tui/render.py`, replace `_render_pretty`:

```python
def _render_pretty(rows, group_by_list, today=None):
    if not rows:
        return f"{_DIM}(nothing){_RESET}"

    today = today or datetime.date.today()
    numbered = any(row.get("number") is not None for row in rows)
    num_width = len(str(len(rows))) if numbered else 0

    def one(row):
        prefix = ""
        if numbered and row.get("number") is not None:
            prefix = f"{row['number']:>{num_width}}  "
        indent = "  " + "  " * row["depth"]
        glyph = _DONE_GLYPH if row["done"] else _OPEN_GLYPH
        star = _STAR_GLYPH if row["starred"] and group_by_list is False else ""
        text = f"{prefix}{indent}{glyph} {star}{row['title']}"
        due = row.get("due")
        if due:
            stamp = f"due {due.isoformat()}"
            if not row["done"] and due < today:
                stamp = f"{_RED}{stamp}{_RESET}"
            else:
                stamp = f"{_DIM}{stamp}{_RESET}"
            text = f"{text}  {stamp}"
        return text

    if not group_by_list:
        return "\n".join(one(row) for row in rows)

    lines = []
    current = None
    for row in rows:
        if row["list_title"] != current:
            current = row["list_title"]
            if lines:
                lines.append("")
            lines.append(f"{_BOLD}{current}{_RESET}")
        lines.append(one(row))
    return "\n".join(lines)
```

Update the module docstring at the top of `tasks_tui/render.py` — replace:

```python
`render()` accepts an optional `today` to pin the overdue-red comparison in
pretty mode; when the caller does not pass one, it defaults to the system
date (`datetime.date.today()`).
"""
```

with:

```python
`render()` accepts an optional `today` to pin the overdue-red comparison in
pretty mode; when the caller does not pass one, it defaults to the system
date (`datetime.date.today()`).

A row is prefixed with its number in pretty mode if and only if it already
carries a `number` key — plain and JSON output never show it. `cli.py`
assigns numbers when it writes the short-id mapping `done <N>` reads from;
this module has no idea that mapping exists, it only prints what it's
given.
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_render -v`
Expected: PASS, 23 + 6 = 29 tests

- [ ] **Step 5: Verify nothing regressed**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: PASS, 139 + 6 = 145 tests

- [ ] **Step 6: Commit**

```bash
git add tasks_tui/render.py tests/test_render.py
git commit -m "feat: add opt-in row numbering to pretty-mode output"
```

---

## Task 4: `cli.py` — assign numbers and write the mapping

**Files:**
- Modify: `tasks_tui/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `shortids.write` (Task 2), `render.py`'s opt-in `number` key
  (Task 3)
- Produces: every listing verb (`fav`, `list`, `today`, `overdue`,
  `search`) now assigns `row["number"] = i` (1-based, matching print order)
  to each row it renders, and writes the mapping via `shortids.write`
  immediately after `render.render` succeeds, before `_emit`.

**Where this goes:** in `run()`, right before the existing
`text = render.render(rows, mode, group_by_list=group, sync_info=info)`
line — `rows` is, by that point, the final, already-sorted row list shared
by all five listing verbs (`list <name>`'s `_list_rows` result, or the
sorted `_rows(...)` result for the other four). Numbering and the mapping
must come from that exact same list, in that exact same order, or `done N`
could act on the wrong task.

- [ ] **Step 1: Write the failing tests**

`_CliCase` in `tests/test_cli.py` needs to manage `GTASK_SHORT_IDS_FILE`
too, or these new tests (and every future test that runs a listing verb)
would write to the developer's real `~/.gtask/last_ids.json`. Replace the
existing `_CliCase` class:

```python
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
```

`TestListVerbSubtasks` builds its own cache fixture and does not inherit
`_CliCase`, so it needs the same `GTASK_SHORT_IDS_FILE` handling — replace
its `setUp`/`tearDown`:

```python
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
```

That class's two existing indentation assertions now break, because a
number prefix will land before the indent once this task's `cli.py` change
ships. Replace them (same method, `test_child_follows_parent_immediately_and_is_indented`):

```python
    def test_child_follows_parent_immediately_and_is_indented(self):
        _, out, _ = self.run_cli(["list", "Work", "-a"])
        lines = out.splitlines()
        parent_idx = next(i for i, ln in enumerate(lines) if "Parent A" in ln)
        child_idx = next(i for i, ln in enumerate(lines) if "Child of A" in ln)
        self.assertEqual(child_idx, parent_idx + 1)
        # The number prefix comes before the depth indent (Task 3), so
        # indentation now shows up as extra space *after* the number rather
        # than at the start of the line — compare each row's text after its
        # number instead of the raw line prefix.
        parent_body = lines[parent_idx].split(None, 1)[1]
        child_body = lines[child_idx].split(None, 1)[1]
        self.assertTrue(child_body.startswith("    "))
        self.assertFalse(parent_body.startswith("    "))
```

Now the new mapping-writing tests. Append to `tests/test_cli.py`, above
`if __name__ == "__main__":`:

```python
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
        out_stream = _TTYStringIO()
        err_stream = io.StringIO()
        cli.run(["fav"], stdout=out_stream, stderr=err_stream)
        out = out_stream.getvalue()
        mapping = self._read_mapping()
        lines_with_1 = [ln for ln in out.splitlines() if ln.lstrip().startswith("1")]
        self.assertTrue(lines_with_1)
        self.assertIn("Buy milk", lines_with_1[0])  # mapping["1"] is t4
        self.assertEqual(mapping["1"]["task_id"], "t4")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli.TestShortIdMapping -v`
Expected: FAIL — `FileNotFoundError` or similar, since `cli.py` does not
write the mapping file yet.

Run: `.venv/bin/python -m unittest tests.test_cli.TestListVerbSubtasks -v`
Expected: PASS still (the fixture/env changes alone don't change output
yet — numbering isn't wired into `cli.py` until Step 3). This confirms the
setUp/tearDown edit alone is safe before touching production code.

- [ ] **Step 3: Write the implementation**

In `tasks_tui/cli.py`, add the import at the top, alongside the existing
`from . import` block:

```python
from . import shortids
```

Replace the tail of `run()` — currently:

```python
    if args.verb != "list":
        rows = _rows(tasks, include_completed=args.all)
        if group:
            rows.sort(key=lambda row: row["list_title"])

    text = render.render(rows, mode, group_by_list=group, sync_info=info)
    return _emit(text, freshness.format_age(info), args, mode, stdout, stderr)
```

with:

```python
    if args.verb != "list":
        rows = _rows(tasks, include_completed=args.all)
        if group:
            rows.sort(key=lambda row: row["list_title"])

    # Numbers and the mapping come from this exact enumeration, in this
    # exact order — the printed number and what `done <N>` acts on can
    # never diverge, because both are derived from the same pass over the
    # same finished row list.
    mapping = {}
    for i, row in enumerate(rows, start=1):
        row["number"] = i
        mapping[i] = {
            "list_id": row["raw"].get("_list_id"),
            "task_id": row["raw"].get("id"),
        }

    text = render.render(rows, mode, group_by_list=group, sync_info=info)
    shortids.write(mapping)
    return _emit(text, freshness.format_age(info), args, mode, stdout, stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_cli -v`
Expected: PASS, all of `test_cli.py`

- [ ] **Step 5: Verify nothing regressed**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: PASS, 145 + 7 = 152 tests

- [ ] **Step 6: Commit**

```bash
git add tasks_tui/cli.py tests/test_cli.py
git commit -m "feat: write the short-id mapping after every listing verb"
```

---

## Task 5: `done` verb

**Files:**
- Modify: `tasks_tui/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `shortids.read` (Task 2); `TaskService.toggle_task_status`,
  `TaskService.sync_to_google`, `TaskService.get_task` (all pre-existing,
  unmodified, in `tasks_tui/task_service.py`); `queries.display_title`
  (pre-existing)
- Produces: `cli.py`'s `_verb_done(number, stdout, stderr) -> int`; `done`
  wired into `_build_parser()` and dispatched in `run()`

**Testing approach:** `tests/test_history.py:328` already proves the
pattern this task needs — build a `TaskService` that skips `__init__`
entirely so no real credentials or network are touched, then hand it a
fake `googleapiclient` tasks collection and drive the *real*
`toggle_task_status`/`sync_to_google`/`get_task` methods against it. That
test uses `TaskService.__new__(TaskService)` because it never needs
`TaskService()` to be called as a constructor. `_verb_done` *does* call
`TaskService()` for real (`cli.py` has no other way to get one), so these
tests instead monkeypatch `TaskService.__init__` itself — the call
`TaskService()` inside `_verb_done` then runs the patched `__init__`, and
every other method on the instance is the real, unmodified production
code.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`, above `if __name__ == "__main__":`:

```python
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


class _FakeGoogleService:
    def __init__(self, google_state, fail_patch=False):
        self._tasks = _FakeGoogleTasks(google_state, fail_patch=fail_patch)

    def tasks(self):
        return self._tasks


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
        # `sync_to_google()` only calls save_local_data() as its very last
        # line, never reached on a failed push — so `done` must persist the
        # toggle itself, or it would vanish the moment this process exits.
        # Checking the in-memory `data` dict alone cannot prove that; it is
        # the same object the fixture handed in regardless of whether
        # anything was actually written. Re-read the cache file from disk.
        with open(self.cache_path) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["tasks"]["L1"][0]["status"], "completed")


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli.TestDoneHappyPath -v`
Expected: FAIL — argparse rejects `done` as an unrecognized subcommand
(exit 2), not the behavior these tests expect.

- [ ] **Step 3: Write the implementation**

In `tasks_tui/cli.py`, add the `done` subparser inside `_build_parser()`,
after the `sync` line:

```python
    add_common(subparsers.add_parser("sync", help="pull from Google Tasks"))

    done_verb = subparsers.add_parser(
        "done", help="mark a task done and push it to Google"
    )
    done_verb.add_argument(
        "number", type=int,
        help="the number a listing command just printed next to the task",
    )

    return parser
```

Add `_verb_done` after `_verb_sync`:

```python
def _verb_done(number, stdout, stderr):
    """Marks task `number` done and pushes it to Google before returning.

    Needs credentials, so TaskService is imported here, same as
    _verb_sync — never at module scope, so the CLI's read-only verbs never
    pay for it and unicurses isolation is unaffected.
    """
    mapping = shortids.read()
    entry = mapping.get(str(number)) if mapping else None
    if (
        not isinstance(entry, dict)
        or "list_id" not in entry
        or "task_id" not in entry
    ):
        print(
            f"no task numbered {number}; run a list command first",
            file=stderr,
        )
        return EXIT_USAGE
    list_id, task_id = entry["list_id"], entry["task_id"]

    from .task_service import TaskService

    try:
        service = TaskService()
    except Exception as exc:
        print(f"could not connect: {exc}", file=stderr)
        return EXIT_ERROR

    task = service.get_task(list_id, task_id)
    if task is None or task.get("deleted"):
        print("task no longer exists; run a list command again", file=stderr)
        return EXIT_USAGE

    title = queries.display_title(task)
    if task.get("status") == "completed":
        print(f'"{title}" is already done', file=stdout)
        return EXIT_OK

    service.toggle_task_status(list_id, task_id)

    try:
        service.sync_to_google()
    except Exception as exc:
        # sync_to_google() only calls save_local_data() as its very last
        # line, never reached when the push fails — so the toggle above
        # would vanish the moment this process exits unless it is saved
        # here explicitly. There is no CLI verb that pushes without also
        # pulling (tasks-tui sync calls sync_from_google, a pull, which
        # would overwrite this very change), so the message does not
        # suggest one — the TUI's existing flush-on-quit/idle/w is, today,
        # the only thing that pushes a pending local change.
        service.save_local_data()
        print(f'✓ marked "{title}" done locally', file=stdout)
        print(f"✗ could not reach Google: {exc}", file=stderr)
        print("  it will push next time you open the TUI", file=stderr)
        return EXIT_ERROR

    print(f'✓ marked "{title}" done — synced', file=stdout)
    return EXIT_OK
```

Wire dispatch in `run()` — replace:

```python
    if args.verb == "sync":
        return _verb_sync(stdout, stderr)

    data, path = _load_cache(stderr)
```

with:

```python
    if args.verb == "sync":
        return _verb_sync(stdout, stderr)

    if args.verb == "done":
        return _verb_done(args.number, stdout, stderr)

    data, path = _load_cache(stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_cli -v`
Expected: PASS, all of `test_cli.py`, including 9 new `TestDone*` tests

- [ ] **Step 5: Verify nothing regressed**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: PASS, 152 + 9 = 161 tests

- [ ] **Step 6: Verify by hand against a fixture**

`tasks-tui sync` and bare `tasks-tui` must not be run — the first makes
live API calls against a real Google account, the second launches a
full-screen curses UI. Exercise `done` safely with fixtures instead:

```bash
export GTASK_CACHE_FILE=/tmp/done-smoke-cache.json
export GTASK_SHORT_IDS_FILE=/tmp/done-smoke-ids.json
python3 -c "
import json
json.dump({
    'task_lists': [{'id': 'L1', 'title': 'Work'}],
    'tasks': {'L1': [{'id': 't1', 'title': 'Ship CLI', 'status': 'needsAction'}]},
}, open('/tmp/done-smoke-cache.json', 'w'))
"
.venv/bin/python -m tasks_tui.cli list Work   # confirm it prints "1  ○ Ship CLI"
```

Note plain `tasks-tui done 1` at this point would construct a *real*
`TaskService()` and attempt a real sync — do not run it against this
fixture. The unit tests above are what verify `_verb_done`'s logic; this
step only confirms the mapping produced by `list Work` matches what a
human would read off the screen.

```bash
cat /tmp/done-smoke-ids.json   # {"1": {"list_id": "L1", "task_id": "t1"}}
rm -f /tmp/done-smoke-cache.json /tmp/done-smoke-ids.json
unset GTASK_CACHE_FILE GTASK_SHORT_IDS_FILE
```

- [ ] **Step 7: Commit**

```bash
git add tasks_tui/cli.py tests/test_cli.py
git commit -m "feat: add the done command"
```

---

## Task 6: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the finished `done` command from Task 5
- Produces: nothing code-facing

- [ ] **Step 1: Document `done` in the README**

In `README.md`, inside the CLI documentation block added by the earlier
CLI-mode work (immediately after the existing `tasks-tui sync` line),
add:

```markdown
tasks-tui done N            # mark task N done (number from the last listing) and push to Google
```

Immediately below the existing flag paragraph, add a new paragraph:

```markdown
`fav`, `list`, `today`, `overdue`, and `search` number each task in
their pretty-mode output (not in piped/plain or `--json` output — those
are unchanged). `tasks-tui done N` marks that task done and pushes the
change to Google before it returns. The number is only valid until the
next listing command overwrites it — run a listing command, then `done`
right after, don't reuse an old number.

```
$ tasks-tui fav
Home
1    ○ Buy milk
Work
2    ○ Ship CLI mode        due 2026-08-05

$ tasks-tui done 2
✓ marked "Ship CLI mode" done — synced
```

Running `done` on a task that's already done is a safe no-op — it prints
`"<title>" is already done` and does not touch Google.
```

- [ ] **Step 2: Verify the documented commands work end to end**

```bash
export GTASK_CACHE_FILE=/tmp/done-doc-check.json
export GTASK_SHORT_IDS_FILE=/tmp/done-doc-check-ids.json
python3 -c "
import json
json.dump({
    'task_lists': [{'id': 'L1', 'title': 'Work'}],
    'tasks': {'L1': [{'id': 't1', 'title': 'Ship CLI', 'status': 'needsAction'}]},
}, open('/tmp/done-doc-check.json', 'w'))
"
.venv/bin/python -m tasks_tui.cli list Work
cat /tmp/done-doc-check-ids.json
rm -f /tmp/done-doc-check.json /tmp/done-doc-check-ids.json
unset GTASK_CACHE_FILE GTASK_SHORT_IDS_FILE
```

Expected: `list Work` prints `1  ○ Ship CLI`; the mapping file contains
`{"1": {"list_id": "L1", "task_id": "t1"}}`, matching what the README's
example claims.

- [ ] **Step 3: Run the full suite one last time**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: PASS, 161 tests

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the done command"
```

---

## Spec Coverage

| Spec requirement | Task |
|---|---|
| `shortids.py` write/read, path via `local_storage.short_ids_path()` | 1, 2 |
| Every listing verb writes the mapping after rendering | 4 |
| Numbers run sequentially across the whole output, not per group | 3, 4 |
| Number prefix in pretty mode only (spec addendum) | 3 |
| `done` resolves via the mapping, exit 2 on missing/unresolvable number | 5 |
| `TaskService()` construction failure exits 1 | 5 |
| Task no longer exists (deleted since listing) exits 2 | 5 |
| Already-done is a no-op, exit 0, no network call | 5 |
| Toggle + `sync_to_google`, success message, exit 0 | 5 |
| Sync failure keeps the local toggle, exit 1, retry guidance | 5 |
| Single number only, no batching | 5 (parser takes one positional int) |
| Mapping not merged, fully overwritten each listing | 4 |
| `sync_to_google` retry-safety relied upon, not reimplemented | 5 (uses the real method, untouched) |
| README documents the command and its numbering scope | 6 |
