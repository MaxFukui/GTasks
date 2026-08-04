"""Read-only command line interface over the local task cache.

Every verb here reads ~/.gtask/local_tasks.json and prints. Nothing mutates
tasks, and only `sync` needs credentials — which is why it is the only verb
that imports TaskService, and it does so lazily.
"""

import argparse
import datetime
import json
import os
import sys

from . import freshness
from . import local_storage
from . import queries
from . import render

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="tasks-tui",
        description=(
            "Google Tasks in your terminal. Run with no arguments to launch "
            "the full TUI, or use a subcommand for a quick read-only query."
        ),
    )
    subparsers = parser.add_subparsers(dest="verb")

    def add_common(sub):
        sub.add_argument(
            "-a", "--all", action="store_true",
            help="include completed tasks (hidden by default, regardless of "
                 "the TUI's hide_completed setting)",
        )
        sub.add_argument(
            "--json", action="store_true", dest="want_json",
            help="machine-readable output",
        )
        sub.add_argument(
            "-q", "--quiet", action="store_true",
            help="suppress the cache-staleness footer",
        )
        return sub

    def add_list_filter(sub):
        sub.add_argument(
            "-l", "--list", dest="list_name", metavar="NAME",
            help="restrict to one list (partial names allowed)",
        )
        return sub

    add_list_filter(add_common(
        subparsers.add_parser("fav", help="starred tasks across all lists")
    ))
    add_common(subparsers.add_parser("lists", help="all lists with counts"))

    list_verb = add_common(
        subparsers.add_parser("list", help="tasks in one list")
    )
    list_verb.add_argument("name", help="list name (partial names allowed)")

    add_list_filter(add_common(
        subparsers.add_parser("today", help="tasks due today")
    ))
    add_list_filter(add_common(
        subparsers.add_parser("overdue", help="tasks past their due date")
    ))

    search_verb = add_list_filter(add_common(
        subparsers.add_parser("search", help="match title or notes")
    ))
    search_verb.add_argument("query", help="text to look for")

    add_common(subparsers.add_parser("sync", help="pull from Google Tasks"))

    return parser


def _load_cache(stderr):
    """Returns (data, path) or (None, path) after reporting a missing cache."""
    path = local_storage.cache_path()
    if not os.path.exists(path):
        print(
            "no local cache; run 'tasks-tui sync' or launch the TUI first",
            file=stderr,
        )
        return None, path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"cannot read {path}: {exc}", file=stderr)
        return None, path
    if not isinstance(data, dict):
        print(f"cannot read {path}: not a JSON object", file=stderr)
        return None, path
    return data, path


def _scope(data, args):
    """Every task in scope, honouring -l. Raises ListResolutionError."""
    list_name = getattr(args, "list_name", None)
    if list_name:
        target = queries.resolve_list_name(data, list_name)
        title = target.get("title", "Untitled")
        return [
            dict(task, _list_id=target["id"], _list_title=title)
            for task in queries.all_tasks_for_list(data, target["id"])
        ]
    return queries.all_tasks_global(data)


def _rows(tasks, include_completed):
    if not include_completed:
        tasks = queries.without_completed(tasks)
    return [
        queries.to_row(task, task.get("_list_title", "")) for task in tasks
    ]


def _list_rows(data, list_id, title, include_completed):
    """Rows for the `list <name>` verb: each parent immediately followed by
    its own children, indented one level (Google Tasks nests only one level
    deep, so depth never exceeds 1).

    Completed-task filtering is applied per task, not inherited: a parent
    that survives keeps only the children that individually survive, and a
    parent that gets filtered out takes its children with it even if a
    child would otherwise survive on its own — printing that child would
    orphan it under a heading that isn't there.
    """
    rows = []
    for parent in queries.tasks_for_list(data, list_id):
        if not include_completed and parent.get("status") == "completed":
            continue
        tagged_parent = dict(parent, _list_id=list_id, _list_title=title)
        rows.append(queries.to_row(tagged_parent, title, depth=0))
        for child in queries.subtasks(data, list_id, parent.get("id")):
            if not include_completed and child.get("status") == "completed":
                continue
            tagged_child = dict(child, _list_id=list_id, _list_title=title)
            rows.append(queries.to_row(tagged_child, title, depth=1))
    return rows


def _emit(text, footer, args, mode, stdout, stderr):
    if text:
        print(text, file=stdout)
    if footer and not args.quiet and mode != render.JSON:
        print(footer, file=stderr)
    return EXIT_OK


def _verb_lists(data, args, mode, info, stdout, stderr):
    entries = []
    for task_list in queries.task_lists(data):
        tasks = queries.tasks_for_list(data, task_list["id"])
        entries.append(
            {
                "title": task_list.get("title", "Untitled"),
                "undone": len(queries.without_completed(tasks)),
                "total": len(tasks),
            }
        )
    text = render.render_lists(entries, mode, sync_info=info)
    return _emit(text, freshness.format_age(info), args, mode, stdout, stderr)


def _verb_sync(stdout, stderr):
    """The only verb that needs credentials, so TaskService is imported here
    rather than at module scope."""
    from .task_service import TaskService

    try:
        service = TaskService()
        service.initial_sync_completed = False
        service.sync_from_google()
    except Exception as exc:
        print(f"sync failed: {exc}", file=stderr)
        return EXIT_ERROR

    lists = queries.task_lists(service.data)
    total = sum(
        len(queries.all_tasks_for_list(service.data, lst["id"])) for lst in lists
    )
    print(f"synced — {len(lists)} lists, {total} tasks", file=stdout)
    return EXIT_OK


def run(argv, stdout=None, stderr=None):
    """Runs one CLI invocation. Returns an exit code; never calls sys.exit."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed help or the error to the real streams.
        return int(exc.code or 0)

    if not args.verb:
        parser.print_help(file=stdout)
        return EXIT_OK

    if args.verb == "sync":
        return _verb_sync(stdout, stderr)

    data, path = _load_cache(stderr)
    if data is None:
        return EXIT_ERROR

    info = freshness.sync_info(data, path)
    mode = render.pick_mode(
        is_tty=stdout.isatty() if hasattr(stdout, "isatty") else False,
        want_json=args.want_json,
        no_color=bool(os.environ.get("NO_COLOR")),
    )

    if args.verb == "lists":
        return _verb_lists(data, args, mode, info, stdout, stderr)

    try:
        if args.verb == "list":
            target = queries.resolve_list_name(data, args.name)
            title = target.get("title", "Untitled")
            rows = _list_rows(data, target["id"], title, include_completed=args.all)
            group = False
        else:
            tasks = _scope(data, args)
            group = True
    except queries.ListResolutionError as exc:
        message = exc.message
        if exc.candidates:
            message = f"{message}: {', '.join(exc.candidates)}"
        print(f"error: {message}", file=stderr)
        return EXIT_USAGE

    if args.verb == "fav":
        tasks = [task for task in tasks if queries.is_starred(task)]
    elif args.verb == "today":
        tasks = queries.due_on(tasks, datetime.date.today())
    elif args.verb == "overdue":
        tasks = queries.overdue(tasks, datetime.date.today())
    elif args.verb == "search":
        tasks = queries.search(tasks, args.query)

    if args.verb != "list":
        rows = _rows(tasks, include_completed=args.all)
        if group:
            rows.sort(key=lambda row: row["list_title"])

    text = render.render(rows, mode, group_by_list=group, sync_info=info)
    return _emit(text, freshness.format_age(info), args, mode, stdout, stderr)
