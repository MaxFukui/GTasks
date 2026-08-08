"""Turns query rows into text, in one of three modes.

pretty  — a terminal is attached: colour, glyphs, grouped under list headers
plain   — output is piped or NO_COLOR is set: one row per line, no escapes
json    — a script is reading: a single object with tasks and cache metadata

Colours are raw ANSI escapes on purpose. `unicurses` must never be imported
on the CLI path, since importing it initializes terminal state.

`render()` accepts an optional `today` to pin the overdue-red comparison in
pretty mode; when the caller does not pass one, it defaults to the system
date (`datetime.date.today()`).

A row is prefixed with its number in pretty mode if and only if it already
carries a `number` key — plain and JSON output never show it. `cli.py`
assigns numbers when it writes the short-id mapping `done <N>` reads from;
this module has no idea that mapping exists, it only prints what it's
given.
"""

import datetime
import json

PRETTY = "pretty"
PLAIN = "plain"
JSON = "json"

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_RED = "\x1b[31m"

_OPEN_GLYPH = "○"
_DONE_GLYPH = "●"
_STAR_GLYPH = "⭐"


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


def _render_plain(rows, group_by_list):
    if not rows:
        return ""

    title_width = max(len(row["title"]) for row in rows)
    list_width = (
        max(len(row["list_title"]) for row in rows) if group_by_list else 0
    )

    lines = []
    for row in rows:
        box = "[x]" if row["done"] else "[ ]"
        parts = [f"{box} {row['title'].ljust(title_width)}"]
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


def _payload_rows(rows):
    """Builds JSON task items from each row's raw Google fields.

    Unlike the pretty/plain paths, JSON output carries the original task
    dict (id, notes, _list_id, _list_title, ...) rather than the trimmed
    row shape — `raw`, `depth`, and `list_title` never appear in it. `title`,
    `starred`, and `due` are overridden with the row's derived values so a
    JSON consumer never has to parse the star marker back out of the title.
    Building a fresh dict per row means neither the caller's rows nor the
    underlying cache are mutated.
    """
    out = []
    for row in rows:
        item = dict(row["raw"])
        item["title"] = row["title"]
        item["starred"] = row["starred"]
        item["due"] = row["due"].isoformat() if row["due"] else None
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


def render_lists(entries, mode, sync_info=None):
    """Renders the `lists` verb: one list per line with undone/total counts."""
    if mode == JSON:
        payload = dict(sync_info or {})
        payload["lists"] = list(entries)
        return json.dumps(payload, ensure_ascii=False)

    if not entries:
        return "" if mode == PLAIN else f"{_DIM}(no lists){_RESET}"

    width = max(len(entry["title"]) for entry in entries)
    lines = []
    for entry in entries:
        counts = f"{entry['undone']}/{entry['total']}"
        if mode == PLAIN:
            lines.append(f"{entry['title'].ljust(width)}  {counts}")
        else:
            lines.append(
                f"{entry['title'].ljust(width)}  {_DIM}{counts}{_RESET}"
            )
    return "\n".join(lines)
