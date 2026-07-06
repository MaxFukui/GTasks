"""Tests for the activity-tracker history layer (issue #1).

Covers the two binding requirements from the issue:
- Pagination correctness across >100 completions and multiple tasklists.
- The in-memory cache never masks fresh completions: a manual refresh
  always re-hits the API and picks up newly-completed tasks.

Uses a small fake of the googleapiclient "tasks" v1 surface so the tests
run without network or credentials.
"""

import datetime
import unittest

from tasks_tui.history import HistoryService


class _FakeReq:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeTasksCollection:
    """Mimics service.tasks(): list(**kw).execute(), keyed by (list, token)."""

    def __init__(self):
        self._pages = {}  # (tasklist_id, page_token) -> response
        self.calls = []

    def set_pages(self, pages):
        self._pages = dict(pages)

    def list(self, **kw):
        self.calls.append(kw)
        key = (kw.get("tasklist"), kw.get("pageToken"))
        return _FakeReq(self._pages[key])


class _FakeTasklistsCollection:
    def __init__(self, items):
        self._req = _FakeReq({"items": items})

    def list(self):
        return self._req


class _FakeService:
    def __init__(self, tasklists_items):
        self._tl = _FakeTasklistsCollection(tasklists_items)
        self.tasks_collection = _FakeTasksCollection()

    def tasklists(self):
        return self._tl

    def tasks(self):
        return self.tasks_collection


def _task(i, day):
    return {
        "id": f"t{i}",
        "title": f"Task {i}",
        "completed": f"{day.isoformat()}T00:00:00.000Z",
    }


def _page(items, next_token):
    resp = {"items": items}
    if next_token is not None:
        resp["nextPageToken"] = next_token
    return resp


def _build_big_service():
    """Two tasklists: L1 has 250 completions (3 pages), L2 has 5 (1 page)."""
    base = datetime.date(2024, 1, 1)
    l1_tasks = [_task(i, base + datetime.timedelta(days=i)) for i in range(250)]
    l2_tasks = [
        _task(1000 + i, base + datetime.timedelta(days=250 + i))
        for i in range(5)
    ]
    pages = {
        ("L1", None): _page(l1_tasks[:100], "p2"),
        ("L1", "p2"): _page(l1_tasks[100:200], "p3"),
        ("L1", "p3"): _page(l1_tasks[200:], None),
        ("L2", None): _page(l2_tasks, None),
    }
    svc = _FakeService([{"id": "L1"}, {"id": "L2"}])
    svc.tasks_collection.set_pages(pages)
    return svc, l1_tasks, l2_tasks


class PaginationTest(unittest.TestCase):
    def test_paginates_all_pages_and_lists(self):
        svc, l1_tasks, l2_tasks = _build_big_service()
        hs = HistoryService(svc)
        completions = hs.get_completions(
            datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        # No completions silently dropped across 3 pages + a second list.
        self.assertEqual(len(completions), 255)
        titles = {c.title for c in completions}
        self.assertEqual(len(titles), 255)
        self.assertEqual({c.tasklist_id for c in completions}, {"L1", "L2"})

    def test_follows_next_page_token_until_exhausted(self):
        svc, _, _ = _build_big_service()
        hs = HistoryService(svc)
        hs.get_completions(
            datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        calls = svc.tasks_collection.calls
        l1_calls = [c for c in calls if c["tasklist"] == "L1"]
        l2_calls = [c for c in calls if c["tasklist"] == "L2"]
        # L1 must walk three distinct page tokens, L2 only one.
        self.assertEqual([c["pageToken"] for c in l1_calls], [None, "p2", "p3"])
        self.assertEqual([c["pageToken"] for c in l2_calls], [None])
        # maxResults pinned to the API ceiling.
        for c in calls:
            self.assertEqual(c["maxResults"], 100)
            self.assertTrue(c["showCompleted"])
            self.assertTrue(c["showHidden"])
            self.assertIsNotNone(c["completedMin"])
            self.assertIsNotNone(c["completedMax"])

    def test_end_day_completions_are_included(self):
        # completedMax is exclusive on the API, so the query layer pushes it
        # to the day AFTER the requested end; a completion timestamped on the
        # end day itself must therefore be included.
        svc = _FakeService([{"id": "LX"}])
        boundary = datetime.date(2024, 6, 15)
        svc.tasks_collection.set_pages({
            ("LX", None): _page(
                [_task(0, boundary)], None
            ),
        })
        hs = HistoryService(svc)
        completions = hs.get_completions(boundary, boundary)
        self.assertEqual(len(completions), 1)


class CacheFreshnessTest(unittest.TestCase):
    def test_cache_serves_repeated_calls_without_api(self):
        svc, _, _ = _build_big_service()
        hs = HistoryService(svc)
        first = hs.get_completions(
            datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        calls_after_first = len(svc.tasks_collection.calls)
        second = hs.get_completions(
            datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)
        )
        # Cached call must NOT re-hit the API.
        self.assertEqual(len(svc.tasks_collection.calls), calls_after_first)
        self.assertEqual([c.task_id for c in first], [c.task_id for c in second])

    def test_manual_refresh_rehits_api_and_picks_up_new_completion(self):
        # Simulate a fresh completion appearing in the API after the first
        # fetch. Without invalidate(), the cache would mask it. A manual
        # refresh (invalidate + fetch) MUST surface the new completion.
        svc = _FakeService([{"id": "LX"}])
        day = datetime.date(2024, 6, 15)
        base_pages = {("LX", None): _page([_task(0, day)], None)}
        svc.tasks_collection.set_pages(base_pages)

        hs = HistoryService(svc)
        first = hs.get_completions(day, day)
        self.assertEqual(len(first), 1)

        # A new completion lands on the server (not yet visible to cache).
        svc.tasks_collection.set_pages(
            {("LX", None): _page([_task(0, day), _task(1, day)], None)}
        )

        # Without refresh: cache still reports the stale single completion.
        cached = hs.get_completions(day, day, use_cache=True)
        self.assertEqual(len(cached), 1, "cache should mask before refresh")

        # Manual refresh: invalidate then fetch must re-hit the API.
        hs.invalidate()
        refreshed = hs.get_completions(day, day, use_cache=True)
        self.assertEqual(len(refreshed), 2)
        self.assertIn("t1", [c.task_id for c in refreshed])

    def test_use_cache_false_bypasses_cache(self):
        svc = _FakeService([{"id": "LX"}])
        day = datetime.date(2024, 6, 15)
        svc.tasks_collection.set_pages({("LX", None): _page([_task(0, day)], None)})
        hs = HistoryService(svc)
        hs.get_completions(day, day)
        before = len(svc.tasks_collection.calls)
        # use_cache=False must always re-hit the API.
        hs.get_completions(day, day, use_cache=False)
        self.assertGreater(len(svc.tasks_collection.calls), before)


class DerivationTest(unittest.TestCase):
    def test_daily_counts_group_by_utc_date(self):
        svc, _, _ = _build_big_service()
        hs = HistoryService(svc)
        counts = hs.daily_counts(
            datetime.date(2024, 1, 1), datetime.date(2025, 1, 1)
        )
        # 255 distinct UTC days, one completion each.
        self.assertEqual(len(counts), 255)
        self.assertTrue(all(v == 1 for v in counts.values()))

    def test_current_streak_active_and_broken(self):
        today = datetime.datetime(2024, 6, 15, tzinfo=datetime.timezone.utc)
        # Active: completions today, yesterday, and the day before.
        svc = _FakeService([{"id": "LX"}])
        days = [today.date() - datetime.timedelta(days=i) for i in range(3)]
        svc.tasks_collection.set_pages(
            {("LX", None): _page([_task(i, d) for i, d in enumerate(days)], None)}
        )
        hs = HistoryService(svc, now=today)
        self.assertEqual(hs.current_streak(), 3)

        # Broken: last completion 5 days ago -> streak is 0.
        old = [today.date() - datetime.timedelta(days=5 + i) for i in range(2)]
        svc2 = _FakeService([{"id": "LX"}])
        svc2.tasks_collection.set_pages(
            {("LX", None): _page([_task(i, d) for i, d in enumerate(old)], None)}
        )
        hs2 = HistoryService(svc2, now=today)
        self.assertEqual(hs2.current_streak(), 0)
        # But recency (days since) is still derivable for the glyph.
        self.assertEqual(hs2.days_since_last_completion(), 5)

    def test_heatmap_grid_structure_is_sunday_first(self):
        today = datetime.datetime(2024, 6, 19, tzinfo=datetime.timezone.utc)
        # 2024-06-19 is a Wednesday.
        svc = _FakeService([{"id": "LX"}])
        svc.tasks_collection.set_pages({("LX", None): _page([], None)})
        hs = HistoryService(svc, now=today)
        grid, labels, start, end = hs.heatmap_grid(weeks=4)
        self.assertEqual(len(grid), 4)
        for week in grid:
            self.assertEqual(len(week), 7)
            # Every column starts on a Sunday.
            self.assertEqual(week[0][0].weekday(), 6)  # Sunday
        self.assertEqual(labels, ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
        self.assertEqual(end, today.date())


if __name__ == "__main__":
    unittest.main()
