# CLI Mode for tasks-tui — Design

Date: 2026-08-04
Status: Approved for planning

## Problem

`tasks-tui` today has exactly one behavior: launch the full curses TUI. Getting a
single piece of information — "what is starred right now?", "what is in my Work
list?" — costs a full TUI launch, navigation, and quit.

The goal is a read-only query mode on the *same* command, so common questions are
answered in one line of terminal input and roughly 30 milliseconds. Inspiration is
taskwarrior: subcommands, plain output, composable with pipes.

## Scope

**In scope (v1):** read-only queries plus an explicit sync.

**Out of scope (v1):** any mutation of tasks — no add, no complete, no delete, no
modify. Writes need a stable public addressing scheme for tasks (ID or index),
which neither the TUI nor the service layer currently exposes. That is its own
design.

## Command Surface

```
tasks-tui                        launch TUI (unchanged)
tasks-tui fav                    starred tasks, all lists, grouped by list
tasks-tui lists                  list names + (undone/total) counts
tasks-tui list <name>            tasks in one list
tasks-tui today                  due today, all lists
tasks-tui overdue                due before today, not completed
tasks-tui search <query>         substring on title + notes, all lists
tasks-tui sync                   pull from Google (only verb needing auth)
tasks-tui --help / --version
```

Bare `tasks-tui` with no arguments keeps its current behavior exactly. Nothing
about the TUI changes from the user's point of view.

### Flags

| Flag | Effect |
|---|---|
| `-a`, `--all` | include completed tasks (default: hidden) |
| `--json` | machine-readable output; implies plain, suppresses stderr footer |
| `-l`, `--list <name>` | restrict `fav` / `today` / `overdue` / `search` to one list |
| `-q`, `--quiet` | suppress the staleness footer |

### Completed tasks are hidden by default

The `hide_completed` key in `~/.gtask/config.json` is a TUI toggle. The CLI
ignores it and always defaults to hiding completed tasks. Rationale: a one-shot
query that prints yesterday's finished items is noise. `-a` opts back in. This is
a deliberate divergence from the config file and must be documented in `--help`.

### List name resolution

Applies to `list <name>` and `-l <name>`. Three tiers, first hit wins:

1. Case-insensitive exact match
2. Case-insensitive prefix match, if unique
3. Case-insensitive substring match, if unique

Ambiguous or no match exits 2 and prints candidates to stderr:

```
$ tasks-tui list wo
error: 'wo' matches 2 lists: Work, Workout
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success, including a query with zero results |
| 1 | runtime error — unreadable cache, sync failure |
| 2 | usage error — bad flag, unresolvable list name |

### Missing cache

If `~/.gtask/local_tasks.json` does not exist (user has never launched the TUI),
exit 1 with stderr:

```
no local cache; run 'tasks-tui sync' or launch the TUI first
```

Never print silent empty output in this case — an empty result and an absent
cache are different states and must look different.

## Architecture

```
tasks_tui/
  queries.py        NEW      pure functions over the cache dict; no auth, no curses
  cli.py            NEW      argparse dispatch + renderers
  main.py           CHANGED  cli() dispatches: no subcommand -> TUI, else cli.run()
  task_service.py   CHANGED  read methods delegate to queries.py
```

### Why `queries.py` exists

`TaskService.__init__` calls `get_credentials()` and `build()` — OAuth token
handling and API discovery. The read-only path must never pay that cost. But the
filtering logic the CLI needs (star detection, deleted exclusion, parent/subtask
separation) currently lives on `TaskService` methods and is therefore reachable
only by constructing one.

The fix is to extract that logic into pure functions taking the cache dict:

```python
# queries.py
def task_lists(data, list_order=None) -> list[dict]
def tasks_for_list(data, list_id, include_completed=False) -> list[dict]
def starred_tasks(data) -> list[tuple[str, dict]]
def all_tasks_global(data) -> list[dict]      # tagged with _list_id / _list_title
def due_on(tasks, date) -> list[dict]
def overdue(tasks, today) -> list[dict]
def search(tasks, query) -> list[dict]
def resolve_list_name(data, name) -> str      # raises on ambiguous / not found
```

`TaskService.get_tasks_for_list` and friends become one-line delegations. Their
names, signatures, and return shapes are unchanged, so the TUI is untouched.

The CLI calls `local_storage.load_data()` then `queries.*` directly. Zero network,
zero OAuth, no `unicurses` import.

### Control flow

```
tasks-tui           -> wrapper(main_loop)                        unchanged path
tasks-tui fav       -> load_data() -> queries -> render -> stdout   (~30ms)
tasks-tui sync      -> TaskService() -> sync_from_google()
```

`sync` is the only verb that constructs a `TaskService`, because it is the only
verb that needs credentials.

## Staleness Reporting

Every query prints how long it has been since the cache last talked to Google.

### Source of the timestamp

`local_tasks.json` mtime is the wrong signal — `save_local_data()` rewrites the
file on every local edit, so mtime measures the last *local write*, not the last
contact with Google.

Instead: a new `last_sync` key (RFC3339 UTC) written into the cache dict by both
`sync_from_google()` and `sync_to_google()`. Those are the only two functions that
touch the API.

Caches written before this change have no such key. Fall back to file mtime and
mark the result approximate.

### Output

The footer goes to **stderr**, so pipes stay clean:

```
$ tasks-tui fav
⭐ Work
  ○ Ship CLI mode        due 2026-08-05
  ○ Review PR
                                    <- stdout ends here
synced 3h ago                       <- stderr, dim
```

```
$ tasks-tui fav | grep Ship
synced 3h ago
  ○ Ship CLI mode        due 2026-08-05
```

Wording by age:

| Age | Line |
|---|---|
| < 60s | `synced just now` |
| < 24h | `synced 3h ago` |
| >= 24h | `synced 2d ago — run 'tasks-tui sync'` (highlighted) |
| no `last_sync` key | `synced ~3h ago (approx)` |
| no cache at all | `never synced — run 'tasks-tui sync'` |

`-q` suppresses the footer. `--json` suppresses it too and puts the same
information in the payload instead:

```json
{"last_sync": "2026-08-04T09:12:03Z", "stale_seconds": 10800, "approx": false, "tasks": []}
```

The `sync` verb prints its own result to stdout: `synced — 4 lists, 61 tasks`.

**Known consequence:** `last_sync` only becomes accurate after the next sync.
Immediately after this ships, every existing cache reports the `~approx` form
until the user syncs once.

## Rendering

One renderer in `cli.py`. Mode is chosen once at startup: `pretty`, `plain`, or
`json`.

```python
def render(rows, mode, group_by_list: bool) -> str
```

`rows` is a uniform list of dicts: `{title, done, due, notes, list_title,
starred}`. Every verb produces `rows`; the renderer contains nothing
verb-specific. `fav`, `search`, `today`, and `overdue` pass `group_by_list=True`.
`list <name>` passes `False`, since the header already names the list.

### pretty (stdout is a TTY)

```
⭐ Work
  ○ Ship CLI mode        due 2026-08-05
  ● Review PR
```

`○` open, `●` done, `⭐` prefixed on starred rows in views other than `fav`. Due
dates are right-aligned, and the due column is omitted entirely when no row in the
group has one. Overdue dates render red.

Colors use raw ANSI escape constants. No new dependency, and critically
`unicurses` must not be imported on the CLI path — importing it initializes
terminal state.

### plain (stdout is piped, or `NO_COLOR` is set)

One row per line, no ANSI, no box-drawing characters, list name in parentheses,
stable column order so `awk` works:

```
[ ] Ship CLI mode  (Work)  due 2026-08-05
[x] Review PR      (Work)
```

### json

```json
{"last_sync": "...", "stale_seconds": 0, "approx": false, "tasks": [...]}
```

Tasks carry their raw Google fields plus `_list_id` and `_list_title`. The `⭐`
marker is stripped from `title` and surfaced as a boolean `starred` field —
machine consumers should not have to parse a marker out of a string.

### Mode detection

`sys.stdout.isatty()` selects pretty vs plain. `NO_COLOR` in the environment
forces plain. `--json` overrides both.

### Subtasks

`list <name>` renders subtasks indented under their parent, matching the TUI's
mental model. `fav`, `today`, `overdue`, and `search` render flat, because they
cross list boundaries and a hierarchy would be misleading. Subtasks are still
*matched* by those verbs — they are just printed flat, labeled with their parent's
list.

## Testing

Three layers, tested independently.

### Layer 1 — `queries.py`

Pure functions over a dict. Tests build a fake cache inline and assert on the
return value. No mocks, no network, no curses.

Cases:

- a starred task is returned by `starred_tasks`; an unstarred one is not
- tasks marked `deleted` never appear in any result
- completed tasks are hidden by default, present with `include_completed=True`
- subtasks (with a `parent` field) are excluded from `tasks_for_list`, included in
  `all_tasks_global`
- name resolution: exact beats prefix, prefix beats substring, ambiguous raises

### Layer 2 — due-date filtering

The one genuinely subtle part, so it gets dedicated tests.

Google stores `due` as an RFC3339 timestamp pinned to midnight UTC. For a user in
UTC−3, a task due "August 5" is stored as `2026-08-05T00:00:00.000Z`, which is
August 4th at 21:00 local. Comparing raw instants would place that task in
"today" a day early.

Correct behavior: convert the stored value to a calendar date and compare calendar
dates, never instants.

Tests pin a fake "now", set a non-UTC timezone, and check the boundary with three
tasks — due today, due tomorrow, due yesterday.

### Layer 3 — renderer and dispatch

The renderer is asserted against expected strings for a fixed row list in each of
the three modes.

Dispatch is tested by calling `run(argv)` as a Python function and capturing
stdout and stderr — no subprocess, no shell. This also covers exit codes and
confirms the staleness footer lands on stderr rather than stdout.

All tests follow the style of `tests/test_history.py`, currently the only test
file in the repo.

## Risk

**The `task_service.py` delegation refactor touches code the TUI uses on every
keystroke.** If a delegation subtly changes filtering behavior, the TUI breaks and
the new tests will not catch it, because they exercise `queries.py` directly.

Mitigations, in order:

1. Delegations stay mechanical — same method name, same signature, same return
   shape; each body becomes a single `return queries.x(self.data, ...)` call.
2. The existing filtering logic moves into `queries.py` verbatim rather than being
   rewritten.
3. Manual TUI smoke test before commit: open it, switch lists, toggle a task
   complete, open Favorites, confirm the counts still match.
