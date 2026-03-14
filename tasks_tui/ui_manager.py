# ui_manager.py - The View Layer
# Handles all screen drawing, window splitting, and curses-specific logic.
# It receives data from the main application logic and draws it.
# It should not contain any Google Tasks API interaction logic.

from unicurses import *
from dateutil.parser import isoparse
import time
import threading


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
        init_pair(5, COLOR_BLUE, COLOR_BLACK)  # Selected

    def _draw_border(self, win, title):
        """Draws a simple box border and title."""
        wborder(win)
        title_str = f" {title} "
        mvwaddstr(win, 0, 2, title_str, color_pair(3) | A_BOLD)

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
    ):
        h, w = getmaxyx(self.stdscr)

        # 1. Calculate window sizes
        list_width = max(
            25, w // 4
        )  # Lists take up at least 25 chars or 1/4th of the screen
        task_width = w - list_width

        # 2. Create window objects
        # Lists Window (Left Panel)
        list_win = newwin(h, list_width, 0, 0)
        # Tasks Window (Right Panel)
        task_win = newwin(h, task_width, 0, list_width)

        # 3. Draw content inside the windows
        self._draw_list_panel(list_win, lists, active_list_id, task_counts)
        self._draw_task_panel(
            task_win, tasks, parent_task, parent_ids, children_counts, hide_completed
        )

        # 4. Refresh all windows
        wrefresh(list_win)
        wrefresh(task_win)

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
                ("c", "Toggle Complete"),
                ("r", "Rename Task"),
                ("a", "Add Due Date"),
                ("i", "Edit Notes"),
                ("d", "Delete Task"),
                ("p", "Paste Task"),
                ("o", "New Task"),
                ("f", "Toggle Hide Done"),
                ("m", "Move Task"),
                ("?", "Close Help"),
            ]

        help_h = len(controls) + 4
        help_w = 60
        help_y = (h - help_h) // 2
        help_x = (w - help_w) // 2

        help_win = newwin(help_h, help_w, help_y, help_x)
        werase(help_win)
        title = "Help - Lists" if active_panel == "lists" else "Help - Tasks"
        self._draw_border(help_win, title)

        for i, (key, desc) in enumerate(controls):
            mvwaddstr(help_win, i + 1, 2, f"{key:<20} {desc}")

        wrefresh(help_win)

    def _draw_list_panel(self, win, lists, active_list_id, task_counts):
        """Draws the Task List titles."""
        werase(win)
        self._draw_border(win, "Lists")
        max_y, max_x = getmaxyx(win)

        for idx, list_item in enumerate(lists):
            list_title = list_item.get("title", "Untitled List")
            list_id = list_item.get("id")
            task_count = task_counts.get(list_id, 0)
            display_title = f"{list_title} ({task_count})"

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

            mvwaddstr(win, y_pos, 1, f"{display_title:<{max_x - 2}}", attr)
            mvwaddstr(win, max_y - 1, 1, "[,] down [.] up [s] reset", A_DIM)

    def _draw_task_panel(
        self,
        win,
        tasks,
        parent_task=None,
        parent_ids=None,
        children_counts=None,
        hide_completed=False,
    ):
        """Draws the individual Tasks."""
        werase(win)
        title = f"Tasks in {parent_task['title']}" if parent_task else "Tasks"
        self._draw_border(win, title)
        max_y, max_x = getmaxyx(win)

        if parent_ids is None:
            parent_ids = set()

        if children_counts is None:
            children_counts = {}

        if not tasks:
            attr = color_pair(5) if self.active_panel == "tasks" else A_DIM
            mvwaddstr(win, 1, 2, "No tasks in this list.", attr)

        for idx, task in enumerate(tasks):
            task_title = task.get("title", "Untitled Task")
            status = task.get("status", "needsAction")
            is_selected = self.active_panel == "tasks" and idx == self.selected_task_idx
            y_pos = idx + 1  # Start drawing content on line 1

            if y_pos >= max_y - 2:
                break  # Avoid drawing off the screen

            attr = A_NORMAL
            symbol = "[ ]"

            if status == "completed":
                attr = color_pair(2)
                symbol = "[X]"

            if is_selected:
                attr = color_pair(5)

            # Pad the title to ensure highlight fills the line
            due_date_str = ""
            if "due" in task:
                try:
                    # Google Tasks API returns 'due' in RFC 3339 format
                    due_date = isoparse(task["due"])
                    due_date_str = f" (Due: {due_date.strftime('%Y-%m-%d')})"
                except ValueError:
                    due_date_str = " (Invalid Date)"

            note_indicator = "*" if "notes" in task and task["notes"] else " "
            children_count = children_counts.get(task["id"], 0)
            has_children_indicator = (
                f" ({children_count})" if children_count > 0 else ""
            )

            display_line = f"{symbol} {note_indicator}{task_title}{due_date_str}{has_children_indicator}"
            # Truncate if too long, ensuring space for selection highlight
            mvwaddstr(win, y_pos, 1, display_line[: max_x - 2], attr)

        # Draw hide_completed indicator
        filter_text = "[f] show done" if hide_completed else "[f] hide done"
        mvwaddstr(win, max_y - 1, max_x - 15, filter_text, A_DIM)

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

    def get_user_input(self, prompt="Input: "):
        """
        Gets a text string from the user at the bottom of the screen.
        This is a common helper function needed in curses applications.
        """
        h, w = getmaxyx(self.stdscr)
        input_win = newwin(1, w, h - 1, 0)
        wmove(input_win, 0, 0)
        waddstr(input_win, prompt, color_pair(0))
        wrefresh(input_win)

        input_string = ""
        try:
            keypad(input_win, True)
            echo()
            input_string = wgetstr(input_win)
            noecho()
        finally:
            werase(input_win)
            wrefresh(input_win)
            delwin(input_win)

        if isinstance(input_string, bytes):
            return input_string.decode("utf-8")
        return input_string

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
