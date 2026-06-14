# ui_manager.py - The View Layer
# Handles all screen drawing, window splitting, and curses-specific logic.
# It receives data from the main application logic and draws it.
# It should not contain any Google Tasks API interaction logic.

from unicurses import *
from dateutil.parser import isoparse
import time
import datetime
import tempfile
import threading
import subprocess
import os
import re
import unicodedata
from tasks_tui.task_service import is_starred, display_title

CP_STARRED = 9  # Yellow — starred task indicator


def display_width(text):
    """Returns the terminal column width of text, counting wide chars (emoji, CJK) as 2."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def truncate_to_width(text, width):
    """Truncates text so its terminal display width does not exceed `width`."""
    result = []
    total = 0
    for c in text:
        w = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if total + w > width:
            break
        result.append(c)
        total += w
    return "".join(result)


def fuzzy_match(pattern, text):
    """
    Fuzzy match pattern against text.
    Returns (score, matched) tuple. Higher score = better match.
    Score is 0 if no match.
    """
    if not pattern:
        return (1, True)

    pattern = pattern.lower()
    text = text.lower()

    # Check if all characters in pattern appear in text in order
    pattern_idx = 0
    text_idx = 0
    score = 0
    consecutive_bonus = 0

    while pattern_idx < len(pattern) and text_idx < len(text):
        if pattern[pattern_idx] == text[text_idx]:
            # Character match
            score += 1
            # Bonus for consecutive matches
            if text_idx > 0 and pattern_idx > 0:
                score += consecutive_bonus
                consecutive_bonus = min(consecutive_bonus + 1, 3)
            else:
                consecutive_bonus = 1
            # Bonus for matching at word boundaries
            if text_idx == 0 or text[text_idx - 1] in " _-":
                score += 2
            pattern_idx += 1
        else:
            consecutive_bonus = 0
        text_idx += 1

    if pattern_idx == len(pattern):
        # All pattern characters found in order
        # Bonus for shorter text (more precise match)
        score += max(0, 20 - len(text))
        return (score, True)

    return (0, False)


def get_version_info():
    """Get version from pyproject.toml and git commit hash."""
    version = "unknown"
    commit_hash = "unknown"

    # Try to read version from pyproject.toml
    try:
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        if os.path.exists(pyproject_path):
            with open(pyproject_path, "r") as f:
                for line in f:
                    if line.startswith("version"):
                        version = line.split("=")[1].strip().strip('"')
                        break
    except Exception:
        pass

    # Try to get git commit hash
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        if result.returncode == 0:
            commit_hash = result.stdout.strip()
    except Exception:
        pass

    return version, commit_hash


class UIManager:
    """
    Manages the curses screen layout and drawing.
    """

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.setup_colors()
        self.active_panel = "lists"  # 'lists' or 'tasks'
        self.selected_list_idx = 0
        self.selected_task_idx = 0
        self.syncing = False
        self.animation_thread = None
        self.show_help = False
        self.animation_frame = ""
        self.hide_completed = False
        self.pending_g = False  # chord state for 'gg'

    def setup_colors(self):
        """Initializes color pairs for the TUI."""
        # Use simple color pairs suitable for a terminal
        start_color()
        init_pair(1, COLOR_BLACK, COLOR_WHITE)  # Highlight
        init_pair(2, COLOR_GREEN, COLOR_BLACK)  # Completed
        init_pair(3, COLOR_CYAN, COLOR_BLACK)  # Header
        init_pair(4, COLOR_YELLOW, COLOR_BLACK)  # Active List
        init_pair(5, COLOR_BLACK, COLOR_BLUE)  # Selected - high contrast
        init_pair(6, COLOR_MAGENTA, COLOR_BLACK)  # Subtask header
        init_pair(7, COLOR_CYAN, COLOR_BLACK)  # Subtask text
        init_pair(8, COLOR_WHITE, COLOR_BLUE)  # Subtask completed
        init_pair(9, COLOR_YELLOW, COLOR_BLACK)  # Starred task

    def _draw_border(self, win, title, color_pair_idx=3):
        """Draws a box border and title with optional color."""
        wattron(win, color_pair(color_pair_idx))
        box(win, 0, 0)
        wattroff(win, color_pair(color_pair_idx))
        title_str = f" {title} "
        mvwaddstr(win, 0, 2, title_str, color_pair(color_pair_idx) | A_BOLD)

    def draw_layout(
        self,
        lists,
        tasks,
        active_list_id,
        task_counts,
        parent_task=None,
        parent_ids=None,
        children_counts=None,
        hide_completed=False,
        selected_task=None,
        subtasks=None,
        preview_list_id=None,
        show_starred=False,
        show_favorites=False,
        is_dirty=False,
    ):
        h, w = getmaxyx(self.stdscr)

        # 1. Calculate window sizes
        list_width = max(
            25, w // 4
        )  # Lists take up at least 25 chars or 1/4th of the screen
        task_width = w - list_width

        # Determine bottom panel: subtasks take priority, then notes
        bottom_panel_height = 0
        show_notes_panel = False
        if subtasks and len(subtasks) > 0:
            bottom_panel_height = min(len(subtasks) + 2, h // 3)
        elif selected_task and selected_task.get("notes"):
            note_lines = selected_task["notes"].splitlines()
            bottom_panel_height = min(len(note_lines) + 3, h // 3)
            show_notes_panel = True

        # 2. Create window objects
        # Lists Window (Left Panel)
        list_win = newwin(h - bottom_panel_height, list_width, 0, 0)
        # Tasks Window (Right Panel)
        task_win = newwin(h - bottom_panel_height, task_width, 0, list_width)
        # Bottom Panel (subtasks or notes)
        bottom_win = None
        if bottom_panel_height > 0:
            bottom_win = newwin(bottom_panel_height, w, h - bottom_panel_height, 0)

        # 3. Draw content inside the windows
        self._draw_list_panel(list_win, lists, active_list_id, task_counts)
        self._draw_task_panel(
            task_win,
            tasks,
            parent_task,
            parent_ids,
            children_counts,
            hide_completed,
            preview_list_id=preview_list_id,
            show_starred=show_starred,
            show_favorites=show_favorites,
            is_dirty=is_dirty,
        )

        # Draw bottom panel if available
        if bottom_win:
            if show_notes_panel:
                self._draw_notes_panel(bottom_win, selected_task)
            else:
                self._draw_subtask_panel(bottom_win, subtasks, selected_task)

        # 4. Refresh all windows
        wrefresh(list_win)
        wrefresh(task_win)
        if bottom_win:
            wrefresh(bottom_win)

        if self.show_help:
            self._draw_help_panel(self.active_panel)

    def _draw_help_panel(self, active_panel):
        """Draws a help panel with controls specific to the active panel."""
        h, w = getmaxyx(self.stdscr)

        if active_panel == "lists":
            controls = [
                ("q", "Quit and Sync"),
                ("w", "Write and Sync"),
                ("h/j/k/l", "Select List"),
                ("/", "Search Lists"),
                (",", "Move Down"),
                (".", "Move Up"),
                ("s", "Reset Order"),
                ("r", "Rename List"),
                ("d", "Delete List"),
                ("p", "Paste List"),
                ("o", "New List"),
                ("?", "Close Help"),
                ("", ""),
                ("Note:", "⭐ Favorites is always at top"),
            ]
        else:
            controls = [
                ("q", "Quit and Sync"),
                ("w", "Write and Sync"),
                ("h/j/k/l", "Select Task"),
                ("/", "Search Tasks (/ again: all lists)"),
                ("c", "Toggle Complete"),
                ("r", "Rename Task"),
                ("a", "Add Due Date"),
                ("i", "Edit Notes"),
                ("d", "Delete Task"),
                ("p", "Paste Task"),
                ("o", "New Task (quick)"),
                ("O", "New Task (full form)"),
                ("f", "Toggle Hide Done"),
                ("m", "Move Task"),
                ("s", "Star/Unstar Task"),
                ("*", "Toggle Starred View"),
                ("?", "Close Help"),
            ]

        help_h = len(controls) + 6
        help_w = 60
        help_y = (h - help_h) // 2
        help_x = (w - help_w) // 2

        help_win = newwin(help_h, help_w, help_y, help_x)
        werase(help_win)
        title = "Help - Lists" if active_panel == "lists" else "Help - Tasks"
        self._draw_border(help_win, title)

        for i, (key, desc) in enumerate(controls):
            mvwaddstr(help_win, i + 1, 2, f"{key:<20} {desc}")

        # Add version and commit info at the bottom
        version_line = len(controls) + 2
        version, commit_hash = get_version_info()
        mvwaddstr(help_win, version_line, 2, "-" * 56)
        mvwaddstr(
            help_win, version_line + 1, 2, f"Version: {version} ({commit_hash})", A_DIM
        )

        wrefresh(help_win)

    def _draw_list_panel(self, win, lists, active_list_id, task_counts):
        """Draws the Task List titles."""
        werase(win)
        # Use color 3 (cyan) if lists panel is active, else color 4 (yellow)
        border_color = 3 if self.active_panel == "lists" else 4
        self._draw_border(win, "Lists", border_color)
        max_y, max_x = getmaxyx(win)

        for idx, list_item in enumerate(lists):
            list_title = list_item.get("title", "Untitled List")
            list_id = list_item.get("id")
            is_special = list_item.get("_is_special", False)

            undone, total = task_counts.get(list_id, (0, 0))
            list_display = f"{list_title} ({undone}/{total})"

            is_active = list_item["id"] == active_list_id
            is_selected = self.active_panel == "lists" and idx == self.selected_list_idx
            y_pos = idx + 1  # Start drawing content on line 1

            if y_pos >= max_y - 1:
                break  # Avoid drawing off the screen

            attr = A_NORMAL
            if is_selected:
                # High contrast selection - takes priority over everything
                attr |= color_pair(5)
            elif is_special:
                attr |= color_pair(6)  # Magenta for special lists like Favorites
            elif is_active:
                attr |= color_pair(4)  # Yellow for the currently loaded list

            mvwaddstr(win, y_pos, 1, f"{list_display:<{max_x - 2}}", attr)
            mvwaddstr(win, max_y - 1, 1, "[,] down [.] up [s] reset", A_DIM)

    def _draw_task_panel(
        self,
        win,
        tasks,
        parent_task=None,
        parent_ids=None,
        children_counts=None,
        hide_completed=False,
        preview_list_id=None,
        show_starred=False,
        show_favorites=False,
        is_dirty=False,
    ):
        """Draws the individual Tasks."""
        werase(win)
        if show_favorites:
            title = "⭐ Favorites"
        elif show_starred:
            title = "⭐ Starred"
        elif parent_task:
            title = f"Tasks in {parent_task['title']}"
        elif preview_list_id:
            title = "Tasks (Preview)"
        else:
            title = "Tasks"
        if is_dirty:
            title += " ●"
        border_color = 3 if self.active_panel == "tasks" else 4
        self._draw_border(win, title, border_color)
        max_y, max_x = getmaxyx(win)

        if parent_ids is None:
            parent_ids = set()

        if children_counts is None:
            children_counts = {}

        if not tasks:
            attr = color_pair(5) if self.active_panel == "tasks" else A_DIM
            msg = "No starred tasks." if show_starred else "No tasks in this list."
            mvwaddstr(win, 1, 2, msg, attr)
            return

        for idx, task in enumerate(tasks):
            task_title = display_title(task)  # Strip ⭐ from display
            starred = is_starred(task)
            status = task.get("status", "needsAction")
            is_selected = self.active_panel == "tasks" and idx == self.selected_task_idx
            has_children = task.get("id") in parent_ids
            y_pos = idx + 1

            if y_pos >= max_y - 2:
                break

            # Determine base color
            if status == "completed":
                symbol = "✓"
                attr = color_pair(2)  # Green
            elif starred:
                symbol = "○"
                attr = color_pair(CP_STARRED) | A_BOLD  # Yellow bold for starred
            else:
                symbol = "○"
                attr = A_NORMAL

            # Selected always overrides with blue
            if is_selected:
                attr = color_pair(5)

            # Star indicator shown separately so non-starred tasks align cleanly
            star_indicator = "⭐" if starred else "  "

            # Due date
            due_date_str = ""
            if "due" in task:
                try:
                    due_date = isoparse(task["due"])
                    due_date_str = f" {due_date.strftime('%m/%d')}"
                except ValueError:
                    pass

            note_indicator = "📝" if "notes" in task and task["notes"] else ""

            children_count = children_counts.get(task["id"], 0)
            children_indicator = (
                f" ⤵{children_count}" if has_children and children_count > 0 else ""
            )

            display_line = f"{symbol} {star_indicator}{note_indicator}{task_title}{due_date_str}{children_indicator}"

            list_suffix = (
                f" @ {task['_list_title']}" if task.get("_list_title") else ""
            )
            if list_suffix:
                total = max_x - 2
                suffix_len = len(list_suffix)
                available_for_title = total - suffix_len
                if len(display_line) <= available_for_title:
                    mvwaddstr(win, y_pos, 1, display_line, attr)
                else:
                    main_line = display_line[: available_for_title - 1] + "…"
                    mvwaddstr(win, y_pos, 1, main_line, attr)
                # Use getyx so curses tells us the real column after wide chars (e.g. ⭐)
                _, x_cur = getyx(win)
                if x_cur + suffix_len < max_x:
                    mvwaddstr(win, y_pos, x_cur, list_suffix, A_DIM)
            else:
                mvwaddstr(win, y_pos, 1, display_line[: max_x - 2], attr)

        # Bottom hints
        filter_text = "[f] show done" if hide_completed else "[f] hide done"
        mvwaddstr(win, max_y - 1, max_x - 15, filter_text, A_DIM)
        star_hint = "[*] all lists" if show_starred else "[*] starred"
        mvwaddstr(win, max_y - 1, 1, star_hint, A_DIM)

    def _draw_subtask_panel(self, win, subtasks, selected_task):
        """Draws the subtasks panel at the bottom."""
        werase(win)

        # Draw colored border (magenta)
        wattron(win, color_pair(6))
        box(win, 0, 0)
        wattroff(win, color_pair(6))

        title = (
            f" Subtasks: {selected_task.get('title', 'Unknown')} "
            if selected_task
            else " Subtasks "
        )
        mvwaddstr(win, 0, 2, title, color_pair(6) | A_BOLD)

        max_y, max_x = getmaxyx(win)

        # Show count in the corner
        count_str = f"({len(subtasks)})"
        mvwaddstr(win, 0, max_x - len(count_str) - 2, count_str, color_pair(6) | A_BOLD)

        if not subtasks:
            mvwaddstr(win, 1, 2, "No subtasks", A_DIM)
            return

        for idx, task in enumerate(subtasks):
            task_title = task.get("title", "Untitled Task")
            status = task.get("status", "needsAction")
            due = task.get("due", "")

            # Determine symbol and color based on status
            if status == "completed":
                symbol = "✓"
                attr = color_pair(2)  # Green
            else:
                symbol = "○"
                attr = color_pair(7)  # Cyan

            # Build due date string if present
            due_str = ""
            if due:
                try:
                    due_date = isoparse(due)
                    due_str = f" {due_date.strftime('%m/%d')}"
                except ValueError:
                    pass

            # Build display line with indentation
            display_line = f"  {symbol} {task_title}{due_str}"
            mvwaddstr(win, idx + 1, 1, display_line[: max_x - 2], attr)

        # Draw help text at bottom of panel
        help_text = "[Enter] open  [c] toggle  [d] delete"
        mvwaddstr(win, max_y - 1, 1, help_text, A_DIM)

    def _draw_notes_panel(self, win, task):
        """Draws the notes panel at the bottom for the selected task."""
        werase(win)
        max_y, max_x = getmaxyx(win)

        wattron(win, color_pair(3))
        box(win, 0, 0)
        wattroff(win, color_pair(3))

        title = f" 📝 Notes: {display_title(task)} "
        mvwaddstr(win, 0, 2, title[: max_x - 4], color_pair(3) | A_BOLD)

        notes = task.get("notes", "")
        lines = []
        for raw_line in notes.splitlines():
            # Word-wrap each source line to fit the panel width
            while len(raw_line) > max_x - 4:
                lines.append(raw_line[: max_x - 4])
                raw_line = raw_line[max_x - 4 :]
            lines.append(raw_line)

        for idx, line in enumerate(lines):
            y = idx + 1
            if y >= max_y - 1:
                break
            mvwaddstr(win, y, 2, line)

        mvwaddstr(win, max_y - 1, 1, "[i] edit notes", A_DIM)

    def update_task_selection(self, tasks, direction):
        """Moves the task selection cursor (up/down)."""
        if self.active_panel != "tasks" or not tasks:
            return

        max_idx = len(tasks) - 1
        new_idx = self.selected_task_idx + direction

        if new_idx < 0:
            self.selected_task_idx = 0
        elif new_idx > max_idx:
            self.selected_task_idx = max_idx
        else:
            self.selected_task_idx = new_idx

    def update_list_selection(self, lists, direction):
        """Moves the list selection cursor (up/down)."""
        if self.active_panel != "lists" or not lists:
            return

        max_idx = len(lists) - 1
        new_idx = self.selected_list_idx + direction

        if new_idx < 0:
            self.selected_list_idx = 0
        elif new_idx > max_idx:
            self.selected_list_idx = max_idx
        else:
            self.selected_list_idx = new_idx

    def toggle_panel(self):
        """Switches between the list panel and the task panel."""
        self.active_panel = "tasks" if self.active_panel == "lists" else "lists"

    def toggle_help(self):
        """Toggles the help display."""
        self.show_help = not self.show_help

    def get_user_input(self, prompt="Input: ", default=""):
        """
        Gets a text string from the user at the bottom of the screen.
        Supports editing with backspace and cursor visibility.
        """
        h, w = getmaxyx(self.stdscr)
        input_win = newwin(1, w, h - 1, 0)

        input_string = list(default)  # Use list for easy character manipulation
        cursor_pos = len(input_string)

        def redraw():
            werase(input_win)
            wmove(input_win, 0, 0)
            waddstr(input_win, prompt, color_pair(0))
            waddstr(input_win, "".join(input_string), color_pair(0))
            wmove(input_win, 0, len(prompt) + cursor_pos)
            wrefresh(input_win)

        try:
            keypad(input_win, True)
            noecho()
            curs_set(1)  # Show cursor
            redraw()

            while True:
                key = wgetch(input_win)

                if key in [ord("\n"), ord("\r"), KEY_ENTER]:
                    # Enter pressed - confirm input
                    break
                elif key == 27:  # Escape
                    # Cancel input, return original default
                    input_string = list(default)
                    break
                elif key in [KEY_BACKSPACE, 127, 8]:  # Backspace
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        input_string.pop(cursor_pos)
                        redraw()
                elif key == KEY_LEFT:
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        wmove(input_win, 0, len(prompt) + cursor_pos)
                        wrefresh(input_win)
                elif key == KEY_RIGHT:
                    if cursor_pos < len(input_string):
                        cursor_pos += 1
                        wmove(input_win, 0, len(prompt) + cursor_pos)
                        wrefresh(input_win)
                elif key == KEY_HOME:
                    cursor_pos = 0
                    wmove(input_win, 0, len(prompt) + cursor_pos)
                    wrefresh(input_win)
                elif key == KEY_END:
                    cursor_pos = len(input_string)
                    wmove(input_win, 0, len(prompt) + cursor_pos)
                    wrefresh(input_win)
                elif key == KEY_DC:  # Delete key
                    if cursor_pos < len(input_string):
                        input_string.pop(cursor_pos)
                        redraw()
                elif 32 <= key <= 126:  # Printable characters
                    input_string.insert(cursor_pos, chr(key))
                    cursor_pos += 1
                    redraw()

            curs_set(0)  # Hide cursor
        finally:
            werase(input_win)
            wrefresh(input_win)
            delwin(input_win)

        return "".join(input_string)

    def show_temporary_message(self, message):
        h, w = getmaxyx(self.stdscr)
        mvwaddstr(self.stdscr, h - 2, 1, message, A_REVERSE)
        refresh()
        time.sleep(1)
        # Clear the line
        mvwaddstr(self.stdscr, h - 2, 1, " " * (len(message) + 1))
        refresh()

    def show_list_selector(self, task_lists, active_list_id):
        """Shows a modal to select a task list for moving a task."""
        available_lists = [lst for lst in task_lists if lst["id"] != active_list_id]

        if not available_lists:
            return None

        selected_idx = 0

        while True:
            h, w = getmaxyx(self.stdscr)
            modal_h = len(available_lists) + 4
            modal_w = max(30, w // 3)
            modal_y = (h - modal_h) // 2
            modal_x = (w - modal_w) // 2

            modal_win = newwin(modal_h, modal_w, modal_y, modal_x)
            keypad(modal_win, True)
            werase(modal_win)
            wborder(modal_win)
            mvwaddstr(modal_win, 0, 2, " Move to: ", color_pair(3) | A_BOLD)

            for idx, lst in enumerate(available_lists):
                y_pos = idx + 1
                if idx == selected_idx:
                    mvwaddstr(
                        modal_win,
                        y_pos,
                        1,
                        f"> {lst.get('title', 'Untitled')}",
                        color_pair(5),
                    )
                else:
                    mvwaddstr(modal_win, y_pos, 1, f"  {lst.get('title', 'Untitled')}")

            mvwaddstr(modal_win, modal_h - 2, 1, "[Enter] select  [Esc] cancel", A_DIM)
            wrefresh(modal_win)

            key = wgetch(modal_win)

            if key == KEY_UP or key == ord("k"):
                selected_idx = max(0, selected_idx - 1)
            elif key == KEY_DOWN or key == ord("j"):
                selected_idx = min(len(available_lists) - 1, selected_idx + 1)
            elif key in [ord("\n"), ord("\r"), KEY_ENTER]:
                delwin(modal_win)
                return available_lists[selected_idx]["id"]
            elif key in [27, ord("q"), ord("c")]:  # Escape
                delwin(modal_win)
                return None

            delwin(modal_win)

    def show_fuzzy_search(
        self,
        items,
        title="Search",
        expand_items=None,
        expand_title=None,
        expand_items_all=None,
    ):
        """Shows a fuzzy search interface for finding items.

        If expand_items is given, pressing '/' once switches the search to that
        item set (e.g. searching across every list instead of just the current
        one), keeping the query typed so far. expand_items is expected to exclude
        completed tasks; if expand_items_all is also given, pressing 'f' while
        expanded toggles between that pending-only set and the full set (including
        completed tasks). Returns (expanded, original_idx, show_completed).
        """
        search_query = ""
        selected_idx = 0
        expanded = False
        show_completed = False

        while True:
            h, w = getmaxyx(self.stdscr)
            modal_h = min(20, h - 4)
            modal_w = min(60, w - 4)
            modal_y = (h - modal_h) // 2
            modal_x = (w - modal_w) // 2

            modal_win = newwin(modal_h, modal_w, modal_y, modal_x)
            keypad(modal_win, True)
            werase(modal_win)
            wborder(modal_win)
            mvwaddstr(modal_win, 0, 2, f" {title} ", color_pair(3) | A_BOLD)

            # Filter items based on search query
            if search_query:
                scored_items = []
                for idx, item in enumerate(items):
                    title_text = item.get("title", "Untitled")
                    score, matched = fuzzy_match(search_query, title_text)
                    if matched:
                        scored_items.append((score, idx, item))
                # Sort by score (highest first)
                scored_items.sort(key=lambda x: x[0], reverse=True)
                filtered_items = [(idx, item) for _, idx, item in scored_items]
            else:
                filtered_items = [(i, item) for i, item in enumerate(items)]

            # Display search query
            mvwaddstr(modal_win, 1, 1, f"> {search_query}", color_pair(5))
            mvwaddstr(modal_win, 2, 1, "-" * (modal_w - 2))

            # Display results
            max_display = modal_h - 5
            start_idx = max(0, selected_idx - max_display // 2)
            end_idx = min(len(filtered_items), start_idx + max_display)

            for display_idx, (original_idx, item) in enumerate(
                filtered_items[start_idx:end_idx]
            ):
                y_pos = display_idx + 3
                title_text = item.get("title", "Untitled")
                list_suffix = (
                    f" @ {item['_list_title']}" if item.get("_list_title") else ""
                )
                is_selected = start_idx + display_idx == selected_idx
                prefix = "> " if is_selected else "  "
                attr = color_pair(5) if is_selected else 0
                max_text_w = modal_w - 2 - len(prefix)

                if list_suffix:
                    avail = max(max_text_w - len(list_suffix), 0)
                    if display_width(title_text) > avail:
                        title_text = truncate_to_width(title_text, max(avail - 1, 0)) + "…"
                else:
                    title_text = truncate_to_width(title_text, max_text_w)

                mvwaddstr(modal_win, y_pos, 1, f"{prefix}{title_text}", attr)
                if list_suffix:
                    # Use getyx so curses tells us the real column after wide chars (e.g. ⭐)
                    _, x_cur = getyx(modal_win)
                    if x_cur + len(list_suffix) < modal_w:
                        mvwaddstr(modal_win, y_pos, x_cur, list_suffix, A_DIM)

            # Show count
            count_str = f"({selected_idx + 1}/{len(filtered_items)})"
            mvwaddstr(
                modal_win, modal_h - 2, modal_w - len(count_str) - 2, count_str, A_DIM
            )
            footer = "[Enter] select  [Esc] cancel"
            if expand_items is not None and not expanded:
                footer += "  [/] search all"
            if expanded and expand_items_all is not None:
                footer += "  [f] show done" if not show_completed else "  [f] hide done"
            mvwaddstr(modal_win, modal_h - 2, 1, footer, A_DIM)

            wrefresh(modal_win)

            key = wgetch(modal_win)

            if key == KEY_UP or key == ord("k"):
                selected_idx = max(0, selected_idx - 1)
            elif key == KEY_DOWN or key == ord("j"):
                selected_idx = min(len(filtered_items) - 1, selected_idx + 1)
            elif key in [ord("\n"), ord("\r"), KEY_ENTER]:
                delwin(modal_win)
                if filtered_items:
                    # Return original index
                    return (expanded, filtered_items[selected_idx][0], show_completed)
                return (expanded, None, show_completed)
            elif key in [27, ord("q")]:  # Escape
                delwin(modal_win)
                return (expanded, None, show_completed)
            elif key == ord("/") and expand_items is not None and not expanded:
                items = expand_items
                title = expand_title or title
                expanded = True
                selected_idx = 0
            elif key == ord("f") and expanded and expand_items_all is not None:
                show_completed = not show_completed
                items = expand_items_all if show_completed else expand_items
                selected_idx = 0
            elif key == KEY_BACKSPACE or key == 127:  # Backspace
                search_query = search_query[:-1]
                selected_idx = 0
            elif 32 <= key <= 126:  # Printable characters
                search_query += chr(key)
                selected_idx = 0

            delwin(modal_win)

    def show_new_task_form(self):
        """
        Full-detail task creation form with vim modal feel.
        Returns {"title", "due", "notes"} or None if cancelled.
        """
        MONTHS = [
            {"title": "01 - January"},  {"title": "02 - February"},
            {"title": "03 - March"},    {"title": "04 - April"},
            {"title": "05 - May"},      {"title": "06 - June"},
            {"title": "07 - July"},     {"title": "08 - August"},
            {"title": "09 - September"},{"title": "10 - October"},
            {"title": "11 - November"}, {"title": "12 - December"},
        ]
        MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun",
                      "Jul","Aug","Sep","Oct","Nov","Dec"]
        LABELS = ["Title", "Due", "Notes"]
        LABEL_W = 12  # "  Title   › " width

        # Mutable state dict avoids nonlocal in nested functions
        s = {
            "field": 0,       # 0=title, 1=due, 2=notes
            "insert": False,
            "title": [],      # list of chars
            "tcursor": 0,
            "due_display": "",
            "due_iso": "",
            "notes": "",
        }

        def draw(win=None):
            """Draw the form, create window if not given."""
            if win:
                delwin(win)
            h, w = getmaxyx(self.stdscr)
            form_h, form_w = 13, min(64, w - 4)
            form_y = (h - form_h) // 2
            form_x = (w - form_w) // 2
            fw = newwin(form_h, form_w, form_y, form_x)
            werase(fw)
            keypad(fw, True)

            # Border: yellow in INSERT, cyan in NORMAL
            bc = color_pair(4) if s["insert"] else color_pair(3)
            wattron(fw, bc | A_BOLD)
            box(fw, 0, 0)
            wattroff(fw, bc | A_BOLD)

            mode = "INSERT" if s["insert"] else "NORMAL"
            mvwaddstr(fw, 0, 2, f" New Task — {mode} ", bc | A_BOLD)

            values = [
                "".join(s["title"]),
                s["due_display"] or "[not set]",
                (s["notes"].splitlines()[0] if s["notes"] else "[no notes]"),
            ]

            row_ys = [2, 5, 8]
            for i, (label, value) in enumerate(zip(LABELS, values)):
                y = row_ys[i]
                label_str = f"  {label:<6}  › "
                val_x = 1 + len(label_str)
                max_val = form_w - val_x - 2
                is_sel = (i == s["field"])

                if is_sel and not s["insert"]:
                    # NORMAL selected: full-row blue
                    mvwaddstr(fw, y, 0, " " * form_w, color_pair(5))
                    mvwaddstr(fw, y, 1, label_str, color_pair(5) | A_BOLD)
                    mvwaddstr(fw, y, val_x, value[:max_val], color_pair(5))
                elif is_sel and s["insert"]:
                    # INSERT selected: full-row yellow
                    mvwaddstr(fw, y, 0, " " * form_w, color_pair(4) | A_DIM)
                    mvwaddstr(fw, y, 1, label_str, color_pair(4) | A_BOLD)
                    if i == 0:
                        # Title: show with cursor
                        scroll = max(0, s["tcursor"] - max_val + 1)
                        disp = "".join(s["title"])[scroll: scroll + max_val]
                        mvwaddstr(fw, y, val_x, disp, color_pair(4))
                        wmove(fw, y, val_x + min(s["tcursor"] - scroll, max_val))
                    else:
                        mvwaddstr(fw, y, val_x, value[:max_val], color_pair(4))
                else:
                    mvwaddstr(fw, y, 1, label_str, A_DIM)
                    mvwaddstr(fw, y, val_x, value[:max_val])

                # Hint line below each field
                if i == 0 and is_sel:
                    hint = "type title, Esc to exit insert" if s["insert"] else "i/Enter → insert"
                    mvwaddstr(fw, y + 1, val_x, hint, A_DIM)
                elif i == 1 and is_sel:
                    mvwaddstr(fw, y + 1, val_x, "i/Enter → pick month › day › year", A_DIM)
                elif i == 2 and is_sel:
                    mvwaddstr(fw, y + 1, val_x, "i/Enter → open $EDITOR (neovim)", A_DIM)

            # Bottom status bar
            if s["insert"] and s["field"] == 0:
                mvwaddstr(fw, form_h - 2, 2, "-- INSERT --", color_pair(4) | A_BOLD)
                curs_set(1)
            else:
                curs_set(0)
            bottom = "[w] save  [q] cancel" if not s["insert"] else "[Esc] normal mode"
            mvwaddstr(fw, form_h - 2, form_w - len(bottom) - 2, bottom, A_DIM)

            wrefresh(fw)
            return fw

        def pick_due():
            _, month_idx, _ = self.show_fuzzy_search(MONTHS, title="Pick Month")
            if month_idx is None:
                return
            month_num = month_idx + 1

            day_str = self.get_user_input("Day (1-31): ")
            if not day_str or not day_str.strip().isdigit():
                return
            day = int(day_str.strip())
            if not (1 <= day <= 31):
                return

            today_year = str(datetime.date.today().year)
            year_str = self.get_user_input("Year: ", default=today_year)
            if not year_str or not year_str.strip().isdigit() or len(year_str.strip()) != 4:
                return
            year = int(year_str.strip())

            try:
                date_obj = datetime.date(year, month_num, day)
                s["due_display"] = f"{MONTH_ABBR[month_idx]} {day:02d} {year}"
                s["due_iso"] = date_obj.isoformat()
            except ValueError:
                self.show_temporary_message(f"Invalid date: {month_num}/{day}/{year}")

        def open_notes_editor():
            with tempfile.NamedTemporaryFile(
                suffix=".md", delete=False, mode="w+", encoding="utf-8"
            ) as tf:
                tf.write(s["notes"])
                tmp = tf.name
            editor = os.environ.get("EDITOR", "vim")
            def_prog_mode()
            endwin()
            subprocess.call([editor, tmp])
            reset_prog_mode()
            doupdate()
            with open(tmp, "r", encoding="utf-8") as tf:
                s["notes"] = tf.read().rstrip()
            os.remove(tmp)

        win = None
        try:
            while True:
                win = draw(win)
                key = wgetch(win)

                if not s["insert"]:
                    # ── NORMAL MODE ──────────────────────────────────
                    if key in [ord("j"), KEY_DOWN]:
                        s["field"] = min(2, s["field"] + 1)
                    elif key in [ord("k"), KEY_UP]:
                        s["field"] = max(0, s["field"] - 1)
                    elif key in [ord("i"), ord("\n"), ord("\r"), KEY_ENTER]:
                        if s["field"] == 0:
                            s["insert"] = True
                        elif s["field"] == 1:
                            pick_due()
                        elif s["field"] == 2:
                            open_notes_editor()
                    elif key == ord("w"):
                        if s["title"]:
                            return {
                                "title": "".join(s["title"]),
                                "due": s["due_iso"],
                                "notes": s["notes"],
                            }
                        self.show_temporary_message("Title is required to save")
                    elif key in [27, ord("q")]:
                        return None
                else:
                    # ── INSERT MODE (title field only) ────────────────
                    if key == 27:  # Esc → normal
                        s["insert"] = False
                    elif key in [ord("\n"), ord("\r"), KEY_ENTER]:
                        s["insert"] = False
                    elif key in [KEY_BACKSPACE, 127, 8]:
                        if s["tcursor"] > 0:
                            s["tcursor"] -= 1
                            s["title"].pop(s["tcursor"])
                    elif key == KEY_DC:
                        if s["tcursor"] < len(s["title"]):
                            s["title"].pop(s["tcursor"])
                    elif key == KEY_LEFT:
                        s["tcursor"] = max(0, s["tcursor"] - 1)
                    elif key == KEY_RIGHT:
                        s["tcursor"] = min(len(s["title"]), s["tcursor"] + 1)
                    elif key == KEY_HOME:
                        s["tcursor"] = 0
                    elif key == KEY_END:
                        s["tcursor"] = len(s["title"])
                    elif 32 <= key <= 126:
                        s["title"].insert(s["tcursor"], chr(key))
                        s["tcursor"] += 1
        finally:
            if win:
                delwin(win)
            curs_set(0)

    def _sync_animation(self):
        """The actual animation loop to be run in a thread."""
        braille_patterns = ["⣷", "⣯", "⣟", "⡿", "⢿", "⣻", "⣽", "⣾"]
        i = 0
        h, w = getmaxyx(self.stdscr)
        while self.syncing:
            animation_frame = f" {braille_patterns[i % len(braille_patterns)]} Syncing"
            mvwaddstr(self.stdscr, h - 2, 1, animation_frame, A_NORMAL)
            refresh()
            time.sleep(0.1)
            i += 1

    def start_sync_animation(self):
        """Starts the sync animation in a separate thread."""
        if not self.syncing:
            self.syncing = True
            nodelay(self.stdscr, True)
            self.animation_thread = threading.Thread(target=self._sync_animation)
            self.animation_thread.start()

    def stop_sync_animation(self):
        """Stops the sync animation."""
        if self.syncing:
            self.syncing = False
            self.animation_thread.join()
            nodelay(self.stdscr, False)
            h, w = getmaxyx(self.stdscr)
            mvwaddstr(self.stdscr, h - 2, 1, " " * (w - 2))  # Clear the line
            refresh()
