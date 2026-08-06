# `done` Command — Design

Date: 2026-08-05
Status: Approved for planning

## Problem

The CLI query mode (`fav`, `list`, `today`, `overdue`, `search`, `sync`) is
read-only. There is no way to complete a task without opening the TUI. Google
task IDs are long opaque strings, unusable as a command-line argument, so
completing a task by ID is not viable directly.

The goal is `tasks-tui done <N>`, where `N` is a short number a listing
command just printed next to each task — taskwarrior's model for addressing
tasks from the command line.

## Command

```
tasks-tui fav
Work
1    ○ Ship CLI mode        due 2026-08-05
2    ○ Review PR
Home
3    ○ Buy milk

tasks-tui done 2
✓ marked "Review PR" done — synced
```

(Group headers in pretty mode are the plain list title, bold — no star.
Verified against the shipped renderer rather than assumed.)

`N` is ephemeral: it means whatever the most recent listing command printed
at that position. Running another listing command overwrites it.

## Architecture

```
tasks_tui/
  shortids.py    NEW      write/read the number -> (list_id, task_id) mapping
  render.py      CHANGED  opt-in row-number prefix, pretty mode only
  cli.py         CHANGED  every listing verb assigns numbers + writes the
                           mapping; new `done` verb
  local_storage.py CHANGED  short_ids_path(), mirroring cache_path()
```

**Addendum (found during planning, ratified before implementation):** the
example above requires the renderer to print the number somewhere, which
the original draft of this section omitted from the file list. Ratified
scope: the number prefix appears in **pretty mode only** — plain (piped)
output and `--json` output are unchanged by this feature, since plain mode
is what any existing script consuming this CLI's output depends on, and
JSON already carries the real, permanent task `id`, a better identifier
for scripting than an ephemeral number. `render.py`'s existing renderer
prints a row's number if and only if the row already carries a `number`
key — a row without one renders exactly as it does today, so this stays
purely additive to the read-only CLI mode shipped earlier.

Flow:

```
tasks-tui fav        -> render rows -> shortids.write({1: {...}, 2: {...}, ...})
tasks-tui done 2      -> shortids.read() -> TaskService() [needs credentials]
                       -> toggle_task_status(list_id, task_id) -> sync_to_google()
```

`shortids.py` is pure I/O with no business logic:

```python
def write(mapping: dict[int, dict]) -> None
def read() -> dict[int, dict] | None   # None if missing or malformed
```

`shortids.py` resolves its own path by calling
`local_storage.short_ids_path()` internally — callers never pass a path in,
the same division of responsibility `cli.py` already has with
`local_storage.cache_path()` for the main cache.

Every verb that prints individually addressable task rows — `fav`, `list`,
`today`, `overdue`, `search` — writes the mapping after a successful render.
`lists` and `sync` do not, since neither prints addressable tasks. Numbering
is one continuous sequence across the whole printed output, not restarted
per list group, matching what the user reads top-to-bottom on screen.

## Persistence Model

`done` pushes to Google before the command exits — it does not leave the
change pending the way an idle TUI session would. Rationale: a CLI
invocation is a single one-shot process with no idle time to defer through,
unlike the TUI, which flushes dirty changes on quit, on a 30-second idle
timer, or on `w` (`main.py:424-428`). Mirroring that flush-on-exit behavior
is the only way a one-shot command gets the same guarantee.

`sync_to_google()` does not track "what changed since last sync" as a queue
of pending operations — every call diffs the *entire* local cache against
Google's current state, field by field, and pushes whatever differs
(`task_service.py:585-586`, `598-599`). This makes a failed sync safe to
retry *for a long-lived process*: the diff, not a queue, means calling
`sync_to_google()` any number of times sends the same single `patch` call
until it succeeds, never duplicates it.

**Correction (found during Task 5's review, before it was found by a real
user):** the paragraph above described the retry story from the TUI's
point of view, where the process stays alive to see "the next successful
sync." A one-shot CLI command does not stay alive — it has already exited
by the time any such retry could happen. `save_local_data()` only runs as
the *last* line of `sync_to_google()` (`task_service.py:606`), so on a
failed push that line is never reached and the in-memory toggle would
vanish the instant `done` returns, taken with it. The originally-drafted
failure message (`✓ marked "<title>" done locally`) was therefore false —
nothing was actually written to disk — and its suggested recovery,
`run 'tasks-tui sync' to retry`, was actively destructive: `sync` calls
`sync_from_google()` (a *pull*), which would silently overwrite the
(unsaved, and even if saved, un-pushed) local toggle with Google's stale
state.

Ratified fix, minimal scope: on a failed sync, `done` calls
`service.save_local_data()` itself before reporting the failure, so the
toggle survives to disk even though the push didn't land. The failure
message drops the specific-but-wrong retry command; there is currently no
CLI verb that pushes without also pulling, so the honest guidance is that
the change will go out the next time something *does* push — today, that
means the TUI's existing flush-on-quit/idle/`w` behavior
(`main.py:424-428`). Building a CLI-level "push what's pending" verb is a
larger change to the already-shipped `sync` verb's semantics and is
explicitly out of scope for this plan.

## Command Behavior

1. Read the mapping (path from `local_storage.short_ids_path()`, overridable
   via `GTASK_SHORT_IDS_FILE` — same pattern as `GTASK_CACHE_FILE`).
2. Missing file, or `N` not a key in it: exit 2,
   `no task numbered N; run a list command first`. Bucketed with the
   existing "unresolvable reference" usage errors (same class as an
   unresolvable list name in `list <name>`).
3. Construct `TaskService()` — needs credentials, imported lazily inside the
   verb function exactly like `_verb_sync` already does, so `unicurses`
   isolation is unaffected. Construction failure: exit 1, same shape as
   `sync`'s existing failure handling. Note this construction step is
   identical to what `sync` already does, including its existing behavior
   of running a full `sync_from_google()` if the local cache is completely
   empty (`task_service.py:31`) — `done` does not introduce a new case
   here, it inherits `sync`'s.
4. Look up the task in the loaded cache by `(list_id, task_id)`. Not found —
   deleted, or its list removed, since the listing that produced `N`: exit
   2, `task no longer exists; run a list command again`.
5. Already `status == "completed"`: print `"<title>" is already done`, exit
   0. No toggle, no network call. `toggle_task_status` is a toggle, not an
   idempotent "mark done" — a command named `done` must never un-complete a
   task on a second run.
6. Otherwise: `toggle_task_status(list_id, task_id)` — completes it,
   cascades to subtasks per existing behavior — then `sync_to_google()`.
7. Sync succeeds: `✓ marked "<title>" done — synced`, exit 0.
8. Sync fails: `done` calls `save_local_data()` itself so the toggle
   survives to disk, prints `✓ marked "<title>" done locally` /
   `✗ could not reach Google: <reason>` /
   `  it will push next time you open the TUI`, exit 1. The local toggle is
   kept, not rolled back — see the Persistence Model correction above for
   why the toggle must be explicitly saved here, and why the recovery
   guidance points at the TUI rather than at `sync`.

`done` accepts exactly one number. Marking several tasks means running the
command several times — batching is out of scope for v1.

| Exit code | When |
|---|---|
| 0 | Marked done and synced; or already done (no-op) |
| 1 | `TaskService()` construction failed; or sync failed after a successful local toggle |
| 2 | No mapping file, or `N` not in it; or the mapped task no longer exists |

## Mapping File

```
~/.gtask/last_ids.json   (overridable: GTASK_SHORT_IDS_FILE)
{"1": {"list_id": "L1", "task_id": "abc123"},
 "2": {"list_id": "L1", "task_id": "def456"}}
```

- Written only after a successful render, so a crash mid-render never
  leaves a mapping pointing at rows the user never saw.
- Fully overwritten, not merged, by every listing verb — always reflects
  only the most recent listing.
- No locking, no concurrency handling, matching `local_tasks.json`, which
  already has none. Single-user, single-machine tool.
- Missing or malformed file when `done` runs produces the same
  `no task numbered N; run a list command first` message as a genuinely
  absent file — never a crash.
- Task titles are not stored in the mapping. `done` already looks the task
  up in the cache by `(list_id, task_id)` in step 4, so the title it prints
  comes from there — not duplicated in two places that could drift apart.

## Testing

`shortids.py` — pure I/O, no network, no cache dependency: write/read
round-trip; missing file returns `None`, not a crash; malformed JSON
returns `None`, not a crash; the env-var override is honored.

`cli.py`'s `done` verb — reuses the pattern already proven in
`tests/test_history.py:328`: construct a `TaskService` via
`TaskService.__new__(TaskService)` to skip `__init__` (no real credentials,
no network), then assign a fake `googleapiclient` tasks collection to
`.service` and a fixture dict to `.data`. Tests monkeypatch
`tasks_tui.task_service.TaskService` itself before calling
`cli.run(["done", "N"], ...)` — safe because `cli.py` imports `TaskService`
*inside* the verb function, so the patched class is what gets constructed at
call time, not whatever was bound at import time.

Cases to cover: happy path (toggle, sync, exit 0); already-done no-op;
missing mapping file; out-of-range number; task deleted since the listing
that produced the mapping; sync failure leaving the local toggle in place
with exit 1. This also covers `sync`'s network path for the first time,
which Task 6's review flagged as an existing gap `done` would otherwise
inherit.

## Risk

Reusing `TaskService.__new__` for tests is an established pattern, not a
new one — low risk. The one thing worth flagging: `done`'s "already
completed" check (step 5) and its "task not found" check (step 4) both read
from `TaskService.data`, which is loaded from the same on-disk cache the
listing command that produced the mapping read moments earlier. Under
normal single-user, single-machine use these are consistent by construction
— nothing else writes to that file between the two commands. If another
process (a concurrently running TUI, a second terminal) mutates the cache
in between, `done` acts on whatever is on disk at the moment it runs, which
is correct behavior, not a race to guard against, since `local_tasks.json`
already has no concurrency protection anywhere else in the codebase.
