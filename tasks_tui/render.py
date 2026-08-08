"""Turns query rows into text, in one of three modes.

pretty  — a terminal is attached: colour, glyphs, grouped under list headers
plain   — output is piped or NO_COLOR is set: one row per line, no escapes
json    — a script is reading: a single object with tasks and cache metadata

Colours are raw ANSI escapes on purpose. `unicurses` must never be imported
on the CLI path, since importing it initializes terminal state.

`render()` accepts an optional `today` to pin the overdue-red comparison in
pretty mode; when the caller does not pass one, it defaults to the system
date (`datetime.date.today()`).

A row is prefixed with its stable `short_id` in pretty and plain modes when
that key is present. JSON carries `short_id` as a field on each task. The
handle is derived from the Google task id by the caller; this module only
prints what it is given.
"""

import datetime
import json
import re
import shutil

PRETTY = "pretty"
PLAIN = "plain"
JSON = "json"

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_RED = "\x1b[31m"

# Soft 256-color backgrounds for pretty mode only. Tuned for dark terminals;
# plain/JSON never emit them. Header is a touch brighter than zebra so
# section breaks read as bands, not just bold text.
_BG_HEADER = "\x1b[48;5;238m"
_BG_ZEBRA = "\x1b[48;5;236m"

_OPEN_GLYPH = "○"
_DONE_GLYPH = "●"
_STAR_GLYPH = "⭐"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def pick_mode(is_tty, want_json, no_color):
    """json wins over everything; a pipe or NO_COLOR downgrades to plain."""
    if want_json:
        return JSON
    if not is_tty or no_color:
        return PLAIN
    return PRETTY


def _due_text(row):
    due = row.get("due")
    return f"due {due.isoformat()}" if due else ""


def _visible_len(text):
    """Column width of `text` with ANSI SGR sequences removed."""
    return len(_ANSI_RE.sub("", text))


def _term_width():
    try:
        return shutil.get_terminal_size(fallback=(80, 24)).columns
    except Exception:
        return 80


def _paint_bg(text, bg, width):
    """Fill a line with `bg`, padded to `width` visible columns.

    Nested styles inside `text` often emit a full SGR reset (`\x1b[0m`), which
    would also clear the background and leave a hole in the stripe. After
    every reset we re-open `bg` so dim/red/bold spans keep the row band.
    """
    if not bg:
        return text
    pad = max(0, width - _visible_len(text))
    body = text + (" " * pad)
    body = body.replace(_RESET, _RESET + bg)
    return f"{bg}{body}{_RESET}"


def _render_plain(rows, group_by_list):
    if not rows:
        return ""

    title_width = max(len(row["title"]) for row in rows)
    list_width = (
        max(len(row["list_title"]) for row in rows) if group_by_list else 0
    )
    short_width = max(
        (len(row.get("short_id") or "") for row in rows), default=0
    )

    lines = []
    for row in rows:
        box = "[x]" if row["done"] else "[ ]"
        handle = row.get("short_id") or ""
        if short_width:
            head = f"{handle.ljust(short_width)}  {box} {row['title'].ljust(title_width)}"
        else:
            head = f"{box} {row['title'].ljust(title_width)}"
        parts = [head]
        if group_by_list:
            parts.append(f"({row['list_title']})".ljust(list_width + 2))
        due = _due_text(row)
        if due:
            parts.append(due)
        lines.append("  ".join(parts).rstrip())
    return "\n".join(lines)


def _render_pretty(rows, group_by_list, today=None):
    if not rows:
        return f"{_DIM}(nothing){_RESET}"

    today = today or datetime.date.today()
    short_width = max(
        (len(row.get("short_id") or "") for row in rows), default=0
    )

    def one(row):
        prefix = ""
        handle = row.get("short_id") or ""
        if short_width and handle:
            # Dim the handle so the title stays primary; fixed width keeps
            # glyphs aligned across the listing.
            pad = handle.ljust(short_width)
            prefix = f"{_DIM}{pad}{_RESET}  "
        elif short_width:
            prefix = " " * (short_width + 2)
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

    # Build undecorated lines first, then paint backgrounds in a second
    # pass so every band shares one width (longest content line, capped by
    # the terminal) and zebra index is a pure function of task order.
    raw_lines = []  # (kind, text) kind in {"header", "task", "blank"}
    if not group_by_list:
        for row in rows:
            raw_lines.append(("task", one(row)))
    else:
        current = None
        for row in rows:
            if row["list_title"] != current:
                current = row["list_title"]
                if raw_lines:
                    raw_lines.append(("blank", ""))
                raw_lines.append(("header", f"{_BOLD}{current}{_RESET}"))
            raw_lines.append(("task", one(row)))

    content_width = max((_visible_len(text) for _, text in raw_lines if text), default=0)
    width = max(content_width, min(_term_width(), 120))

    painted = []
    task_index = 0
    for kind, text in raw_lines:
        if kind == "blank":
            painted.append("")
        elif kind == "header":
            painted.append(_paint_bg(text, _BG_HEADER, width))
        else:
            bg = _BG_ZEBRA if task_index % 2 == 1 else ""
            painted.append(_paint_bg(text, bg, width) if bg else text)
            task_index += 1
    return "\n".join(painted)


def _payload_rows(rows):
    """Builds JSON task items from each row's raw Google fields.

    Unlike the pretty/plain paths, JSON output carries the original task
    dict (id, notes, _list_id, _list_title, ...) rather than the trimmed
    row shape — `raw`, `depth`, and `list_title` never appear in it. `title`,
    `starred`, `due`, and `short_id` (when present on the row) are set from
    the derived row values so a JSON consumer never has to parse the star
    marker back out of the title or re-hash the Google id. Building a fresh
    dict per row means neither the caller's rows nor the underlying cache
    are mutated.
    """
    out = []
    for row in rows:
        item = dict(row["raw"])
        item["title"] = row["title"]
        item["starred"] = row["starred"]
        item["due"] = row["due"].isoformat() if row["due"] else None
        if row.get("short_id"):
            item["short_id"] = row["short_id"]
        out.append(item)
    return out


def _render_json(rows, sync_info):
    payload = dict(sync_info or {})
    payload["tasks"] = _payload_rows(rows)
    return json.dumps(payload, ensure_ascii=False)


def render(rows, mode, group_by_list, sync_info=None, today=None):
    """Renders task rows. Returns a string with no trailing newline.

    `today` pins the overdue-red comparison in pretty mode; it defaults to
    the system date when not given.
    """
    if mode == JSON:
        return _render_json(rows, sync_info)
    if mode == PLAIN:
        return _render_plain(rows, group_by_list)
    return _render_pretty(rows, group_by_list, today=today)


def _progress_bar(undone, total, width=10, filled="█", empty="░"):
    """Compact bar: filled portion = open/undone share of total.

    Empty lists render an all-empty bar so the column still aligns.
    """
    if width <= 0:
        return ""
    if total <= 0:
        return empty * width
    n_fill = int(round((undone / total) * width))
    n_fill = max(0, min(width, n_fill))
    return filled * n_fill + empty * (width - n_fill)


def render_lists(entries, mode, sync_info=None):
    """Renders the `lists` verb: one list per line with undone/total counts.

    Pretty mode adds a summary header band, zebra rows, right-aligned
    counts, and a small open/total bar so the eye can compare lists at a
    glance. Plain keeps a stable aligned table (no ANSI, ASCII bar).
    """
    if mode == JSON:
        payload = dict(sync_info or {})
        payload["lists"] = list(entries)
        return json.dumps(payload, ensure_ascii=False)

    if not entries:
        return "" if mode == PLAIN else f"{_DIM}(no lists){_RESET}"

    title_width = max(len(entry["title"]) for entry in entries)
    # "N/M" column width shared by plain and pretty so counts line up.
    ratio_width = max(
        len(f"{e['undone']}/{e['total']}") for e in entries
    )
    bar_width = 10

    def row_text(entry, pretty):
        title = entry["title"].ljust(title_width)
        ratio = f"{entry['undone']}/{entry['total']}".rjust(ratio_width)
        bar = _progress_bar(entry["undone"], entry["total"], width=bar_width)
        if not pretty:
            return f"{title}  {ratio}  {bar}"

        # Dim lists with nothing open; bold the name when there is work so
        # the scan path is "bright names = attention".
        idle = entry["undone"] == 0
        if idle:
            title_s = f"{_DIM}{title}{_RESET}"
            ratio_s = f"{_DIM}{ratio}{_RESET}"
            bar_s = f"{_DIM}{bar}{_RESET}"
        else:
            title_s = f"{_BOLD}{title}{_RESET}"
            # Split N/M so the open count stays bright and the total recedes.
            open_part = str(entry["undone"])
            total_part = str(entry["total"])
            core = f"{open_part}{_DIM}/{total_part}{_RESET}"
            pad = max(0, ratio_width - len(f"{open_part}/{total_part}"))
            ratio_s = (" " * pad) + core
            bar_s = f"{_DIM}{bar}{_RESET}"
        return f"{title_s}  {ratio_s}  {bar_s}"

    if mode == PLAIN:
        return "\n".join(row_text(entry, pretty=False) for entry in entries)

    # Pretty: summary header + zebra body, shared paint width.
    total_open = sum(entry["undone"] for entry in entries)
    total_tasks = sum(entry["total"] for entry in entries)
    n_lists = len(entries)
    summary = (
        f"{_BOLD}Lists{_RESET}  "
        f"{_DIM}·  {n_lists} list{'s' if n_lists != 1 else ''}"
        f"  ·  {total_open} open"
        f"  ·  {total_tasks} total{_RESET}"
    )

    body = [row_text(entry, pretty=True) for entry in entries]
    content_width = max(
        [_visible_len(summary), *(_visible_len(line) for line in body)],
        default=0,
    )
    width = max(content_width, min(_term_width(), 120))

    painted = [_paint_bg(summary, _BG_HEADER, width)]
    for i, line in enumerate(body):
        bg = _BG_ZEBRA if i % 2 == 1 else ""
        painted.append(_paint_bg(line, bg, width) if bg else line)
    return "\n".join(painted)
