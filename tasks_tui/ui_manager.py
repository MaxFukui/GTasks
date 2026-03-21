# ui_manager.py - The View Layer
# Handles all screen drawing, window splitting, and curses-specific logic.
# It receives data from the main application logic and draws it.
# It should not contain any Google Tasks API interaction logic.

from unicurses import *
from dateutil.parser import isoparse
import time
import threading
import subprocess
import os
import re
from tasks_tui.task_service import is_starred, display_title

CP_STARRED = 9  # Yellow — starred task indicator


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
    ):
        h, w = getmaxyx(self.stdscr)

        # 1. Calculate window sizes
        list_width = max(
            25, w // 4
        )  # Lists take up at least 25 chars or 1/4th of the screen
        task_width = w - list_width

        # Determine if we need a subtask panel
        subtask_panel_height = 0
        if subtasks and len(subtasks) > 0:
            subtask_panel_height = min(len(subtasks) + 2, h // 3)

        # 2. Create window objects
        # Lists Window (Left Panel)
        list_win = newwin(h - subtask_panel_height, list_width, 0, 0)
        # Tasks Window (Right Panel)
        task_win = newwin(h - subtask_panel_height, task_width, 0, list_width)
        # Subtasks Panel (Bottom)
        subtask_win = None
        if subtask_panel_height > 0:
            subtask_win = newwin(subtask_panel_height, w, h - subtask_panel_height, 0)

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
        )

        # Draw subtask panel if available
        if subtask_win:
            self._draw_subtask_panel(subtask_win, subtasks, selected_task)

        # 4. Refresh all windows
        wrefresh(list_win)
        wrefresh(task_win)
        if subtask_win:
            wrefresh(subtask_win)

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
            ]
        else:
            controls = [
                ("q", "Quit and Sync"),
                ("w", "Write and Sync"),
                ("h/j/k/l", "Select Task"),
                ("/", "Search Tasks"),
                ("c", "Toggle Complete"),
                ("r", "Rename Task"),
                ("a", "Add Due Date"),
                ("i", "Edit Notes"),
                ("d", "Delete Task"),
                ("p", "Paste Task"),
                ("o", "New Task"),
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
            undone, total = task_counts.get(list_id, (0, 0))
            list_display = f"{list_title} ({undone}/{total})"

            is_active = list_item["id"] == active_list_id
            is_selected = self.active_panel == "lists" and idx == self.selected_list_idx
            y_pos = idx + 1  # Start drawing content on line 1

            if y_pos >= max_y - 1:
                break  # Avoid drawing off the screen

            attr = A_NORMAL
            if is_active:
                attr |= color_pair(4)  # Yellow for the currently loaded list
            if is_selected:
                attr |= color_pair(5)

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
    ):
        """Draws the individual Tasks."""
        werase(win)
        if show_starred:
            title = "⭐ Starred"
        elif parent_task:
            title = f"Tasks in {parent_task['title']}"
        elif preview_list_id:
            title = "Tasks (Preview)"
        else:
            title = "Tasks"
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
            children_indicator = f" ⤵{children_count}" if has_children and children_count > 0 else ""

            display_line = f"{symbol} {star_indicator}{note_indicator}{task_title}{due_date_str}{children_indicator}"
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

    def show_fuzzy_search(self, items, title="Search"):
        """Shows a fuzzy search interface for finding items."""
        search_query = ""
        selected_idx = 0

        while True:
            h, w = getmaxyx(self.stdscr)
            modal_h = min(20, h - 4)
            modal_w = min(60, w - 4)
            modal_y = (h - modal_h) // 2
            modal_x = (w - modal_w) // 2

            modal_win = newwin(modal_h, modal_w, modal_y, modal_x)
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

                if start_idx + display_idx == selected_idx:
                    mvwaddstr(
                        modal_win,
                        y_pos,
                        1,
                        f"> {title_text[: modal_w - 4]}",
                        color_pair(5),
                    )
                else:
                    mvwaddstr(modal_win, y_pos, 1, f"  {title_text[: modal_w - 4]}")

            # Show count
            count_str = f"({selected_idx + 1}/{len(filtered_items)})"
            mvwaddstr(
                modal_win, modal_h - 2, modal_w - len(count_str) - 2, count_str, A_DIM
            )
            mvwaddstr(modal_win, modal_h - 2, 1, "[Enter] select  [Esc] cancel", A_DIM)

            wrefresh(modal_win)

            key = wgetch(modal_win)

            if key == KEY_UP or key == ord("k"):
                selected_idx = max(0, selected_idx - 1)
            elif key == KEY_DOWN or key == ord("j"):
                selected_idx = min(len(filtered_items) - 1, selected_idx + 1)
            elif key in [ord("\n"), ord("\r"), KEY_ENTER]:
                delwin(modal_win)
                if filtered_items:
                    return filtered_items[selected_idx][0]  # Return original index
                return None
            elif key in [27, ord("q")]:  # Escape
                delwin(modal_win)
                return None
            elif key == KEY_BACKSPACE or key == 127:  # Backspace
                search_query = search_query[:-1]
                selected_idx = 0
            elif 32 <= key <= 126:  # Printable characters
                search_query += chr(key)
                selected_idx = 0

            delwin(modal_win)

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
