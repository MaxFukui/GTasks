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
from . import shortids

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

    short_id_help = (
        "short id shown next to the task in a listing "
        f"(at least {shortids.MIN_INPUT_LEN} hex chars; unique prefix ok)"
    )

    done_verb = subparsers.add_parser(
        "done", help="mark a task done and push it to Google"
    )
    done_verb.add_argument("short_id", help=short_id_help)

    # star/unstar are the write side of the virtual Favorites list; `fav`
    # remains the read-only listing verb so existing muscle memory is safe.
    star_verb = subparsers.add_parser(
        "star", help="favorite a task (prefix title with ⭐) and push"
    )
    star_verb.add_argument("short_id", help=short_id_help)

    unstar_verb = subparsers.add_parser(
        "unstar", help="remove a task from favorites and push"
    )
    unstar_verb.add_argument("short_id", help=short_id_help)

    add_verb = subparsers.add_parser(
        "add", help="create a task in a list and push it to Google"
    )
    add_verb.add_argument(
        "list_name",
        help="list to add to (partial names allowed, same as `list`)",
    )
    add_verb.add_argument(
        "title",
        nargs="+",
        help="task title (words are joined with spaces)",
    )
    add_verb.add_argument(
        "-s", "--star", action="store_true", dest="star_new",
        help="also favorite the new task",
    )

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


def _rows(tasks, include_completed, data=None, parent_context=False):
    """Build renderer rows. When parent_context is set (fav), starred
    subtasks get `title  ·  parent` so they are not ambiguous when printed
    flat across lists.
    """
    if not include_completed:
        tasks = queries.without_completed(tasks)
    rows = []
    for task in tasks:
        row = queries.to_row(task, task.get("_list_title", ""))
        if parent_context and data is not None:
            parent_title = queries.parent_display_title(
                data, task.get("_list_id"), task
            )
            row["title"] = queries.with_parent_context(row["title"], parent_title)
        rows.append(row)
    return rows


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


def _list_title_for(data, list_id):
    for task_list in data.get("task_lists", []):
        if task_list.get("id") == list_id:
            return task_list.get("title", "Untitled")
    return "Untitled"


def _format_short_candidate(data, list_id, task):
    """One line describing a match for an ambiguous short-id prompt."""
    title = queries.display_title(task)
    parent_title = queries.parent_display_title(data, list_id, task)
    title = queries.with_parent_context(title, parent_title)
    list_title = _list_title_for(data, list_id)
    handle = shortids.short_id(task.get("id"))
    return f"{handle}  {title}  ({list_title})"


def _disambiguate(matches, token, data, stdout, stderr, stdin):
    """Pick one match when a short id prefix hits more than one task.

    Interactive TTY: numbered prompt on stderr, answer on stdin.
    Non-interactive: print candidates and return None (caller exits 2).
    """
    print(f"ambiguous short id '{token}':", file=stderr)
    for i, (list_id, task) in enumerate(matches, start=1):
        print(
            f"  {i}  {_format_short_candidate(data, list_id, task)}",
            file=stderr,
        )

    interactive = (
        hasattr(stdin, "isatty")
        and stdin.isatty()
        and hasattr(stderr, "isatty")
        and stderr.isatty()
    )
    if not interactive:
        print(
            f"ambiguous short id '{token}'; be more specific",
            file=stderr,
        )
        return None

    print(f"which one? [1-{len(matches)}, q cancels] ", end="", file=stderr)
    try:
        stderr.flush()
    except Exception:
        pass
    try:
        answer = stdin.readline()
    except Exception:
        return None
    if not answer:
        print("cancelled", file=stderr)
        return None
    answer = answer.strip().lower()
    if answer in ("", "q", "quit", "n", "no"):
        print("cancelled", file=stderr)
        return None
    if not answer.isdigit():
        print(f"invalid choice '{answer}'", file=stderr)
        return None
    idx = int(answer)
    if idx < 1 or idx > len(matches):
        print(f"invalid choice '{answer}'", file=stderr)
        return None
    return matches[idx - 1]


def _resolve_short_id(raw_token, stdout, stderr, stdin=None):
    """Resolve a typed short id to (list_id, task_snapshot, cache_data)."""
    stdin = stdin or sys.stdin
    token = shortids.normalize_token(raw_token)
    if token is None:
        print(
            f"invalid short id '{raw_token}'; "
            f"use at least {shortids.MIN_INPUT_LEN} hex characters "
            f"(as shown in a listing)",
            file=stderr,
        )
        return None, EXIT_USAGE

    data, _path = _load_cache(stderr)
    if data is None:
        return None, EXIT_ERROR

    matches = shortids.resolve(data, token)
    if not matches:
        print(f"no task matches '{token}'", file=stderr)
        return None, EXIT_USAGE
    if len(matches) > 1:
        chosen = _disambiguate(matches, token, data, stdout, stderr, stdin)
        if chosen is None:
            return None, EXIT_USAGE
        list_id, task = chosen
    else:
        list_id, task = matches[0]
    return (list_id, task, data), EXIT_OK


def _connect_service(stderr):
    """Lazy TaskService construction shared by mutating verbs."""
    from .task_service import TaskService

    try:
        return TaskService(), None
    except Exception as exc:
        print(f"could not connect: {exc}", file=stderr)
        return None, EXIT_ERROR


def _push_or_save_local(service, title_phrase, stdout, stderr):
    """sync_to_google, with the same local-fallback messaging as `done`.

    `title_phrase` is the already-quoted human label used in success lines,
    e.g. 'marked "Ship CLI" done' (without the trailing locally/synced).
    """
    try:
        service.sync_to_google()
    except Exception as exc:
        saved_locally = service.save_local_data()
        if saved_locally:
            print(f"✓ {title_phrase} locally", file=stdout)
            print(f"✗ could not reach Google: {exc}", file=stderr)
            print("  it will push next time you open the TUI", file=stderr)
        else:
            # local_storage.save_data() swallows IOError, so the mutation
            # made it neither to Google nor to disk — nothing is pending
            # anywhere, so the "it will push next time" guidance would be
            # actively wrong here.
            print(
                f"✗ could not save locally or reach Google: {exc}",
                file=stderr,
            )
        return EXIT_ERROR

    print(f"✓ {title_phrase} — synced", file=stdout)
    return EXIT_OK


def _verb_done(raw_token, stdout, stderr, stdin=None):
    """Marks the task addressed by a stable short id done and pushes it."""
    resolved, code = _resolve_short_id(raw_token, stdout, stderr, stdin)
    if resolved is None:
        return code
    list_id, task, _data = resolved
    task_id = task.get("id")

    service, err = _connect_service(stderr)
    if service is None:
        return err

    # Re-fetch from the service's own cache view so we act on what will be
    # synced, not a stale snapshot from the earlier resolve pass.
    live = service.get_task(list_id, task_id)
    if live is None or live.get("deleted"):
        print("task no longer exists; run sync or a listing again", file=stderr)
        return EXIT_USAGE

    title = queries.display_title(live)
    if live.get("status") == "completed":
        print(f'"{title}" is already done', file=stdout)
        return EXIT_OK

    service.toggle_task_status(list_id, task_id)
    return _push_or_save_local(
        service, f'marked "{title}" done', stdout, stderr
    )


def _verb_star(raw_token, want_starred, stdout, stderr, stdin=None):
    """Favorite or unfavorite a task by short id, then push."""
    resolved, code = _resolve_short_id(raw_token, stdout, stderr, stdin)
    if resolved is None:
        return code
    list_id, task, _data = resolved
    task_id = task.get("id")

    service, err = _connect_service(stderr)
    if service is None:
        return err

    live = service.get_task(list_id, task_id)
    if live is None or live.get("deleted"):
        print("task no longer exists; run sync or a listing again", file=stderr)
        return EXIT_USAGE

    title = queries.display_title(live)
    already = queries.is_starred(live)
    if want_starred and already:
        print(f'"{title}" is already starred', file=stdout)
        return EXIT_OK
    if not want_starred and not already:
        print(f'"{title}" is not starred', file=stdout)
        return EXIT_OK

    service.set_starred(list_id, task_id, want_starred)
    if want_starred:
        phrase = f'starred "{title}"'
    else:
        phrase = f'unstarred "{title}"'
    return _push_or_save_local(service, phrase, stdout, stderr)


def _verb_add(list_name, title_words, star_new, stdout, stderr):
    """Create a task in a named list and push it to Google."""
    title = " ".join(title_words).strip()
    if not title:
        print("error: title must not be empty", file=stderr)
        return EXIT_USAGE

    data, _path = _load_cache(stderr)
    if data is None:
        return EXIT_ERROR

    try:
        target = queries.resolve_list_name(data, list_name)
    except queries.ListResolutionError as exc:
        message = exc.message
        if exc.candidates:
            message = f"{message}: {', '.join(exc.candidates)}"
        print(f"error: {message}", file=stderr)
        return EXIT_USAGE

    list_id = target["id"]
    list_title = target.get("title", "Untitled")

    service, err = _connect_service(stderr)
    if service is None:
        return err

    # Prefer the service's live list table in case the on-disk snapshot is
    # slightly behind what TaskService just loaded.
    live_lists = {lst["id"]: lst for lst in service.get_task_lists()}
    if list_id not in live_lists or live_lists[list_id].get("deleted"):
        print(f"error: list '{list_name}' no longer exists", file=stderr)
        return EXIT_USAGE

    new_title = title
    if star_new:
        from .queries import STAR_MARKER

        if not new_title.startswith(STAR_MARKER):
            new_title = STAR_MARKER + new_title

    task = service.add_task(list_id, new_title)
    if task is None:
        print("error: could not create task", file=stderr)
        return EXIT_ERROR

    display = queries.display_title(task)
    handle = shortids.short_id(task.get("id"))
    phrase = f'added "{display}" to {list_title}'
    if handle:
        # temp_ ids still get a short handle so the user can star/done them
        # immediately from the local cache before the next listing.
        phrase = f"{phrase} ({handle})"

    code = _push_or_save_local(service, phrase, stdout, stderr)
    if code == EXIT_OK:
        # After sync the temp id is replaced with a Google id — print the
        # stable short so `done`/`star` work without re-listing if possible.
        live = None
        for t in service.data.get("tasks", {}).get(list_id, []):
            if queries.display_title(t) == display and not t.get("deleted"):
                live = t
        if live is not None:
            new_handle = shortids.short_id(live.get("id"))
            if new_handle and new_handle != handle:
                print(f"  short id: {new_handle}", file=stdout)
    return code


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

    if args.verb == "done":
        return _verb_done(args.short_id, stdout, stderr)

    if args.verb == "star":
        return _verb_star(args.short_id, True, stdout, stderr)

    if args.verb == "unstar":
        return _verb_star(args.short_id, False, stdout, stderr)

    if args.verb == "add":
        return _verb_add(
            args.list_name, args.title, args.star_new, stdout, stderr
        )

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
        rows = _rows(
            tasks,
            include_completed=args.all,
            data=data,
            parent_context=(args.verb == "fav"),
        )
        if group:
            rows.sort(key=lambda row: row["list_title"])

    # Stable short ids are pure functions of each task's Google id — the
    # same handle the renderer prints is what `done <short>` resolves,
    # with no ephemeral last-listing map in between.
    for row in rows:
        row["short_id"] = shortids.short_id(row["raw"].get("id"))

    text = render.render(rows, mode, group_by_list=group, sync_info=info)
    return _emit(text, freshness.format_age(info), args, mode, stdout, stderr)
