"""
History query layer, in-memory cache, and derivation logic for the
activity tracker (heatmap + streak glyph).

DESIGN NOTE (issue #1 deliverable)
==================================
Repo structure understanding (post Step-0 exploration):

- Entry point / controller: ``tasks_tui/main.py`` -> ``cli()`` runs the
  unicurses ``wrapper(main_loop)``. ``AppState`` holds a ``TaskService``
  (model) and a ``UIManager`` (view); ``handle_input()`` maps vim-style
  keys; the main loop draws then handles input each tick.
- Model: ``tasks_tui/task_service.py`` -> ``TaskService`` wraps the Google
  Tasks API client (``self.service = build("tasks","v1", credentials=...)``)
  and keeps a local cache in ``self.data`` persisted via
  ``local_storage.py`` (``~/.gtask/local_tasks.json``).
- View: ``tasks_tui/ui_manager.py`` -> ``UIManager`` draws panels with
  ``unicurses``; color pairs 1-9 are defined in ``setup_colors()``; modal
  loops use ``wgetch``.
- Auth: ``tasks_tui/auth.py`` -> OAuth, returns ``Credentials``.
- Storage: ``tasks_tui/local_storage.py`` -> JSON in ``~/.gtask/`` for
  task data + UI config (``hide_completed``, ``active_list_id``,
  ``list_order``). This is UI state only; the tracker MUST NOT persist
  historical data here.

Where the tracker lives:

- Query layer + cache + derivation: THIS FILE (``tasks_tui/history.py``).
  ``HistoryService`` takes the google API client (``TaskService.service``)
  and fetches completed tasks across all tasklists with full pagination.
- Heatmap view: ``UIManager.show_heatmap`` (new method in
  ``ui_manager.py``), rendered as a full-screen modal toggled by ``H``.
- Streak glyph: rendered in the heatmap view title via
  ``UIManager._streak_glyph_attr``.
- Keybinding: ``H`` wired in ``main.py`` ``handle_input()``.

Source of truth: the Google Tasks API only. No local file writes for
historical data. The in-memory cache is a performance cache, not a data
store, and is invalidated on manual refresh (``r`` inside the heatmap
modal) or app restart.

Date canon: daily counts use the UTC calendar date of each task's
``completed`` timestamp. This guarantees the tracker is identical across
every device the user runs this on regardless of local timezone, per the
issue's device-independence constraint.

API LIMITATION (documented per issue): if a user hard-deletes a task (as
opposed to completing/clearing it), that completion is permanently
unrecoverable from the Google Tasks API — this is an API limitation, not a
bug in this feature. ``showDeleted`` is intentionally NOT requested
because deleted tasks carry no ``completed`` timestamp and would only add
noise, not history.
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    """A single historical task completion derived live from the API."""

    tasklist_id: str
    task_id: str
    title: str
    completed: datetime.datetime  # aware UTC


def _parse_rfc3339(ts: str) -> datetime.datetime | None:
    """Parse a Google Tasks RFC3339 timestamp into an aware UTC datetime.

    Google returns e.g. ``"2024-06-01T00:00:00.000Z"``. We normalize the
    trailing ``Z`` for ``fromisoformat`` and pin naive values to UTC.
    Returns ``None`` for empty / unparseable input.
    """
    if not ts:
        return None
    try:
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _counts_from(completions: list[Completion]) -> dict[datetime.date, int]:
    counts: dict[datetime.date, int] = {}
    for c in completions:
        d = c.completed.date()
        counts[d] = counts.get(d, 0) + 1
    return counts


class HistoryService:
    """Fetches completed-task history from the Google Tasks API with full
    pagination, and derives tracker data (daily counts, streaks).

    Pure query layer — holds no persistent state. An in-memory cache
    memoizes a date range within a single app session to avoid redundant
    network calls when flipping between views. The cache is performance
    only and must never be the only place data lives; ``invalidate()``
    (manual refresh) always forces a fresh API hit.
    """

    MAX_RESULTS = 100  # Google Tasks API maximum per page for tasks.list

    def __init__(self, google_service, now: datetime.datetime | None = None):
        # google_service = the built googleapiclient "tasks" v1 resource
        # (i.e. TaskService.service). Kept as a constructor dependency so
        # the layer is unit-testable with a MagicMock.
        self._service = google_service
        self._now = now or datetime.datetime.now(datetime.timezone.utc)
        self._lock = threading.Lock()
        # Cache keyed by (start_iso, end_iso) -> list[Completion].
        self._cache: dict[tuple[str, str], list[Completion]] = {}
        self._cache_valid: dict[tuple[str, str], bool] = {}

    # ---------------------------------------------------------------- public

    def get_completions(
        self,
        start: datetime.date,
        end: datetime.date,
        use_cache: bool = True,
    ) -> list[Completion]:
        """Return all completions in [start, end] across all tasklists.

        With ``use_cache=True`` returns the cached result if present and
        valid. Manual refresh (``invalidate()`` or ``use_cache=False``)
        always re-hits the API.
        """
        key = (start.isoformat(), end.isoformat())
        with self._lock:
            if use_cache and self._cache_valid.get(key, False):
                return list(self._cache.get(key, []))

        completions = self._fetch_all_completions(start, end)
        with self._lock:
            self._cache[key] = list(completions)
            self._cache_valid[key] = True
        return completions

    def invalidate(self) -> None:
        """Drop the entire in-memory cache (manual refresh)."""
        with self._lock:
            self._cache.clear()
            self._cache_valid.clear()

    def daily_counts(
        self,
        start: datetime.date,
        end: datetime.date,
        use_cache: bool = True,
    ) -> dict[datetime.date, int]:
        """Map each UTC date in [start, end] with >=1 completion -> count."""
        return _counts_from(self.get_completions(start, end, use_cache=use_cache))

    def current_streak(self, use_cache: bool = True) -> int:
        """Consecutive days (ending today or yesterday, UTC) with >=1
        completion. Returns 0 if the streak is broken.
        """
        today = self._now.date()
        start = today - datetime.timedelta(days=365)
        counts = self.daily_counts(start, today, use_cache=use_cache)
        # A "current" streak must end today or yesterday.
        if counts.get(today, 0) == 0 and counts.get(
            today - datetime.timedelta(days=1), 0
        ) == 0:
            return 0
        cursor = (
            today
            if counts.get(today, 0) > 0
            else today - datetime.timedelta(days=1)
        )
        streak = 0
        while counts.get(cursor, 0) > 0:
            streak += 1
            cursor -= datetime.timedelta(days=1)
        return streak

    def days_since_last_completion(self, use_cache: bool = True) -> int | None:
        """Days since the most recent completion day (0 = completed today,
        UTC). Returns ``None`` if there is no completion in the queried
        window at all.
        """
        today = self._now.date()
        start = today - datetime.timedelta(days=365)
        counts = self.daily_counts(start, today, use_cache=use_cache)
        if not counts:
            return None
        last_day = max(counts)
        return (today - last_day).days

    def heatmap_grid(
        self, weeks: int = 53, use_cache: bool = True
    ) -> tuple[list[list[tuple[datetime.date, int]]], list[str], datetime.date, datetime.date]:
        """Build a GitHub-style grid: list of week columns (oldest first),
        each a list of 7 ``(date, count)`` tuples in Sunday->Saturday order.
        Also returns weekday labels (Sunday-first) and the (start, end)
        date range queried.
        """
        today = self._now.date()
        # Align to Sunday-starting weeks. weekday(): Mon=0..Sun=6, so
        # days since the most recent Sunday = (weekday + 1) % 7.
        days_since_sunday = (today.weekday() + 1) % 7
        last_sunday = today - datetime.timedelta(days=days_since_sunday)
        start_sunday = last_sunday - datetime.timedelta(weeks=weeks - 1)
        start = start_sunday
        end = today
        counts = self.daily_counts(start, end, use_cache=use_cache)

        grid: list[list[tuple[datetime.date, int]]] = []
        col_sunday = start_sunday
        while col_sunday <= end:
            week = []
            for d in range(7):
                day = col_sunday + datetime.timedelta(days=d)
                week.append((day, counts.get(day, 0)))
            grid.append(week)
            col_sunday += datetime.timedelta(days=7)

        labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        return grid, labels, start, end

    def completions_from_cache(
        self,
        task_service_data: dict,
        start: datetime.date,
        end: datetime.date,
    ) -> list[Completion]:
        """Derive completions from TaskService.data (already API-synced
        local cache) with ZERO API calls. Same UTC-date canon and
        Completion shape as the API path. The Google Tasks API is still
        the source of truth — this just reads the in-memory copy the app
        already syncs, so it is identical to re-paginating the API but
        instant and quota-free.
        """
        start_ts = datetime.datetime.combine(
            start, datetime.time.min, tzinfo=datetime.timezone.utc
        )
        end_ts = datetime.datetime.combine(
            end + datetime.timedelta(days=1),
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        out: list[Completion] = []
        for list_id, tasks in task_service_data.get("tasks", {}).items():
            for t in tasks:
                if t.get("deleted") or t.get("status") != "completed":
                    continue
                completed_ts = _parse_rfc3339(t.get("completed", ""))
                if completed_ts is None:
                    continue
                if start_ts <= completed_ts < end_ts:
                    out.append(
                        Completion(
                            tasklist_id=list_id,
                            task_id=t.get("id", ""),
                            title=t.get("title", ""),
                            completed=completed_ts,
                        )
                    )
        return out

    def snapshot_from_cache(
        self, task_service_data: dict, weeks: int = 53
    ) -> tuple[list[list[tuple[datetime.date, int]]], int | None]:
        """Cache-derived (grid, days_since) for the persistent strip + the
        default H render. Zero API calls. Mirrors what heatmap_grid +
        days_since_last_completion would return from the API path on the
        same data, so the strip is instant on startup.
        """
        today = self._now.date()
        year_start = today - datetime.timedelta(days=365)
        completions = self.completions_from_cache(
            task_service_data, year_start, today
        )
        counts = _counts_from(completions)

        days_since: int | None
        if not counts:
            days_since = None
        else:
            days_since = (today - max(counts)).days

        days_since_sunday = (today.weekday() + 1) % 7
        last_sunday = today - datetime.timedelta(days=days_since_sunday)
        start_sunday = last_sunday - datetime.timedelta(weeks=weeks - 1)
        grid: list[list[tuple[datetime.date, int]]] = []
        col_sunday = start_sunday
        while col_sunday <= today:
            week = []
            for d in range(7):
                day = col_sunday + datetime.timedelta(days=d)
                week.append((day, counts.get(day, 0)))
            grid.append(week)
            col_sunday += datetime.timedelta(days=7)
        return grid, days_since

    # -------------------------------------------------------------- internals

    def _fetch_all_completions(
        self, start: datetime.date, end: datetime.date
    ) -> list[Completion]:
        """Enumerate all tasklists, paginate completed tasks per list.

        Used only by the explicit ``r`` force-refresh in the H modal (and
        the tests). The default strip + H render go through
        snapshot_from_cache instead to avoid startup API storms.

        ``completedMax`` is exclusive on the API, so we push it to the
        start of the day *after* ``end`` to include all of ``end``.
        """
        start_ts = datetime.datetime.combine(
            start, datetime.time.min, tzinfo=datetime.timezone.utc
        )
        end_ts = datetime.datetime.combine(
            end + datetime.timedelta(days=1),
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        completed_min = start_ts.isoformat().replace("+00:00", "Z")
        completed_max = end_ts.isoformat().replace("+00:00", "Z")

        completions: list[Completion] = []
        tasklists = (
            self._service.tasklists().list().execute().get("items", [])
        )
        for tl in tasklists:
            list_id = tl["id"]
            page_token = None
            while True:
                req = self._service.tasks().list(
                    tasklist=list_id,
                    showCompleted=True,
                    showHidden=True,
                    completedMin=completed_min,
                    completedMax=completed_max,
                    maxResults=self.MAX_RESULTS,
                    pageToken=page_token,
                )
                resp = req.execute()
                for t in resp.get("items", []):
                    completed_ts = _parse_rfc3339(t.get("completed", ""))
                    if completed_ts is None:
                        # Not actually completed / no timestamp: skip. This
                        # is defensive; completedMin/Max should already
                        # restrict to completed tasks.
                        continue
                    completions.append(
                        Completion(
                            tasklist_id=list_id,
                            task_id=t.get("id", ""),
                            title=t.get("title", ""),
                            completed=completed_ts,
                        )
                    )
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        return completions
