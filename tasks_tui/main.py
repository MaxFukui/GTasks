# main.py - The Controller Layer / Entry Point
# Initializes the application, connects the TaskService (Model) and
# the UIManager (View), and runs the main event loop.

from unicurses import *
from .task_service import TaskService
from .ui_manager import UIManager
from . import local_storage
import sys
from dateutil.parser import ParserError, isoparse
import os
import subprocess
import tempfile
from unicurses import wrapper


def open_editor_for_task_notes(stdscr, app_state, ui_manager):
    """Opens an editor for the task notes."""
    selected_task = app_state.tasks[ui_manager.selected_task_idx]
    initial_content = selected_task.get("notes", "")

    editor = os.environ.get("EDITOR", "vim")  # Default to vim

    with tempfile.NamedTemporaryFile(
        suffix=".tmp", delete=False, mode="w+", encoding="utf-8"
    ) as tf:
        tf.write(initial_content)
        temp_path = tf.name

    # Suspend curses and open the editor
    def_prog_mode()
    endwin()
    subprocess.call([editor, temp_path])
    # Resume curses
    reset_prog_mode()
    doupdate()

    with open(temp_path, "r", encoding="utf-8") as tf:
        new_note = tf.read()

    os.remove(temp_path)

    if new_note != initial_content:
        app_state.service.change_detail_task(
            app_state.active_list_id, selected_task["id"], new_note
        )
        app_state.refresh_data()


def is_valid_date(date_str):
    try:
        isoparse(date_str)
        return True
    except (ParserError, ValueError):
        return False


# Global State Management (simplified for TUI)
class AppState:
    """Holds the application's current state and data."""

    def __init__(self, task_service):
        self.service = task_service

        config = local_storage.load_config()
        self.active_list_id = (
            config.get("active_list_id") or self.service.active_list_id
        )
        self.service.set_active_list(self.active_list_id)

        self.list_order = config.get("list_order", [])
        if not self.list_order:
            self.list_order = [
                lst["id"] for lst in self.service.data.get("task_lists", [])
            ]
        self.service.set_list_order(self.list_order)

        self.task_lists = self.service.get_task_lists(self.list_order)

        self.current_parent_task_id = None
        self.filtered_tasks_cache = {}  # Cache for filtered tasks
        self.task_counts = {}
        self.hide_completed = config.get("hide_completed", False)
        self.preview_list_id = self.active_list_id  # Start with active list as preview
        self.tasks = self.get_tasks_for_active_list()
        self.list_buffer = ""
        self.task_buffer = ""
        self.parent_task_id_stack = []
        self.parent_task_idx_stack = []
        self.calculate_task_counts()
        self.show_help = False

    def save_config(self):
        """Saves current configuration to disk."""
        config = {
            "hide_completed": self.hide_completed,
            "active_list_id": self.active_list_id,
            "list_order": self.list_order,
        }
        local_storage.save_config(config)

    def calculate_task_counts(self):
        """Calculates the number of tasks (undone/total) in each list."""
        for task_list in self.task_lists:
            list_id = task_list["id"]
            tasks = self.service.get_tasks_for_list(list_id)
            total = len(tasks)
            undone = len([t for t in tasks if t.get("status") != "completed"])
            self.task_counts[list_id] = (undone, total)

    def get_tasks_for_active_list(self):
        """Retrieves tasks for the active list, using cache if possible."""
        if self.current_parent_task_id:
            tasks = self.service.get_subtasks(
                self.active_list_id, self.current_parent_task_id
            )
        else:
            if (
                self.active_list_id not in self.filtered_tasks_cache
                or self.service.dirty
            ):
                tasks = self.service.get_tasks_for_list(self.active_list_id)
                self.filtered_tasks_cache[self.active_list_id] = tasks
            else:
                tasks = self.filtered_tasks_cache[self.active_list_id]

        if self.hide_completed:
            tasks = [t for t in tasks if t.get("status") != "completed"]
        return tasks

    def get_preview_tasks(self, list_id):
        """Retrieves tasks for previewing a list without making it active."""
        if list_id not in self.filtered_tasks_cache or self.service.dirty:
            tasks = self.service.get_tasks_for_list(list_id)
            self.filtered_tasks_cache[list_id] = tasks
        else:
            tasks = self.filtered_tasks_cache[list_id]

        if self.hide_completed:
            tasks = [t for t in tasks if t.get("status") != "completed"]
        return tasks

    def refresh_data(self):
        """Refreshes all data from the service layer and clears the cache."""
        self.task_lists = self.service.get_task_lists(self.list_order)
        self.filtered_tasks_cache.clear()  # Invalidate the cache
        self.tasks = self.get_tasks_for_active_list()
        self.calculate_task_counts()

    def move_list_up(self, list_idx, ui_manager):
        """Moves a list up in the order."""
        # Use task_lists length for bounds checking (excludes deleted lists)
        if list_idx > 0 and list_idx < len(self.task_lists):
            # Get the actual list IDs from task_lists (not list_order which may have deleted lists)
            list_id_to_move = self.task_lists[list_idx]["id"]
            list_id_above = self.task_lists[list_idx - 1]["id"]
            # Ensure both IDs are in list_order (new lists might not be)
            if list_id_to_move not in self.list_order:
                self.list_order.append(list_id_to_move)
            if list_id_above not in self.list_order:
                self.list_order.append(list_id_above)
            # Find and swap these IDs in list_order
            idx_to_move = self.list_order.index(list_id_to_move)
            idx_above = self.list_order.index(list_id_above)
            self.list_order[idx_to_move], self.list_order[idx_above] = (
                self.list_order[idx_above],
                self.list_order[idx_to_move],
            )
            self.service.set_list_order(self.list_order)
            # Refresh task_lists to match new order
            self.task_lists = self.service.get_task_lists(self.list_order)
            # Update selection
            ui_manager.selected_list_idx = list_idx - 1
            # Update preview to show the list at the new position
            if self.task_lists and 0 <= list_idx - 1 < len(self.task_lists):
                self.preview_list_id = self.task_lists[list_idx - 1]["id"]
            self.save_config()

    def move_list_down(self, list_idx, ui_manager):
        """Moves a list down in the order."""
        # Use task_lists length for bounds checking (excludes deleted lists)
        if list_idx < len(self.task_lists) - 1 and list_idx >= 0:
            # Get the actual list IDs from task_lists (not list_order which may have deleted lists)
            list_id_to_move = self.task_lists[list_idx]["id"]
            list_id_below = self.task_lists[list_idx + 1]["id"]
            # Ensure both IDs are in list_order (new lists might not be)
            if list_id_to_move not in self.list_order:
                self.list_order.append(list_id_to_move)
            if list_id_below not in self.list_order:
                self.list_order.append(list_id_below)
            # Find and swap these IDs in list_order
            idx_to_move = self.list_order.index(list_id_to_move)
            idx_below = self.list_order.index(list_id_below)
            self.list_order[idx_to_move], self.list_order[idx_below] = (
                self.list_order[idx_below],
                self.list_order[idx_to_move],
            )
            self.service.set_list_order(self.list_order)
            # Refresh task_lists to match new order
            self.task_lists = self.service.get_task_lists(self.list_order)
            # Update selection
            ui_manager.selected_list_idx = list_idx + 1
            # Update preview to show the list at the new position
            if self.task_lists and 0 <= list_idx + 1 < len(self.task_lists):
                self.preview_list_id = self.task_lists[list_idx + 1]["id"]
            self.save_config()

    def reset_list_order(self):
        """Resets list order to original Google order."""
        self.list_order = [lst["id"] for lst in self.service.data.get("task_lists", [])]
        self.service.set_list_order(self.list_order)
        self.task_lists = self.service.get_task_lists(self.list_order)
        self.save_config()

    def change_active_list(self, list_id):
        """Updates the active list and fetches new tasks, using the cache."""
        if self.service.set_active_list(list_id):
            self.active_list_id = list_id
            self.current_parent_task_id = None
            self.tasks = self.get_tasks_for_active_list()
            self.save_config()
            return True
        return False


def handle_input(stdscr, app_state, ui_manager):
    """
    Main input handler. Maps key presses to application actions.
    """
    try:
        key = getch()
    except curses.error:
        return True  # Ignore curses errors on getch()

    # Quitting
    if key in [ord("q"), ord("Q")]:
        if app_state.service.dirty:
            ui_manager.start_sync_animation()
            app_state.service.sync_to_google()
            ui_manager.stop_sync_animation()
        return False

    if key == KEY_RESIZE:
        return True  # Triggers a redraw

    # Handle help toggle - process the key normally after toggling help
    if ui_manager.show_help and key == ord("?"):
        ui_manager.toggle_help()
        return True

    # Movement
    if key == KEY_UP or key == ord("k"):
        if ui_manager.active_panel == "tasks":
            ui_manager.update_task_selection(app_state.tasks, -1)
        elif ui_manager.active_panel == "lists":
            ui_manager.update_list_selection(app_state.task_lists, -1)
            # Update preview to show tasks from selected list
            if app_state.task_lists and 0 <= ui_manager.selected_list_idx < len(
                app_state.task_lists
            ):
                selected_list = app_state.task_lists[ui_manager.selected_list_idx]
                app_state.preview_list_id = selected_list["id"]
                ui_manager.selected_task_idx = 0  # Reset task selection for preview
    elif key == KEY_DOWN or key == ord("j"):
        if ui_manager.active_panel == "tasks":
            ui_manager.update_task_selection(app_state.tasks, 1)
        elif ui_manager.active_panel == "lists":
            ui_manager.update_list_selection(app_state.task_lists, 1)
            # Update preview to show tasks from selected list
            if app_state.task_lists and 0 <= ui_manager.selected_list_idx < len(
                app_state.task_lists
            ):
                selected_list = app_state.task_lists[ui_manager.selected_list_idx]
                app_state.preview_list_id = selected_list["id"]
                ui_manager.selected_task_idx = 0  # Reset task selection for preview
    elif key == KEY_LEFT or key == ord("h"):
        if app_state.current_parent_task_id:
            app_state.current_parent_task_id = app_state.parent_task_id_stack.pop()
            app_state.refresh_data()
            if app_state.parent_task_idx_stack:
                ui_manager.selected_task_idx = app_state.parent_task_idx_stack.pop()
        elif ui_manager.active_panel == "tasks":
            ui_manager.toggle_panel()
            # When going back to lists panel, set preview to active list
            app_state.preview_list_id = app_state.active_list_id
    elif key == KEY_RIGHT or key == ord("l"):
        if ui_manager.active_panel == "lists":
            if app_state.task_lists and 0 <= ui_manager.selected_list_idx < len(
                app_state.task_lists
            ):
                selected_list = app_state.task_lists[ui_manager.selected_list_idx]
                if app_state.active_list_id != selected_list["id"]:
                    app_state.change_active_list(selected_list["id"])
                    ui_manager.selected_task_idx = 0  # Reset task selection
                # Clear preview when entering a list
                app_state.preview_list_id = None
                ui_manager.toggle_panel()
        elif ui_manager.active_panel == "tasks" and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            app_state.parent_task_id_stack.append(app_state.current_parent_task_id)
            app_state.parent_task_idx_stack.append(ui_manager.selected_task_idx)
            app_state.current_parent_task_id = selected_task["id"]
            app_state.refresh_data()
            ui_manager.selected_task_idx = 0

    # Fuzzy search (only in lists panel for now)
    if ui_manager.active_panel == "lists" and app_state.task_lists:
        if key == ord("/"):
            result_idx = ui_manager.show_fuzzy_search(
                app_state.task_lists, title="Search Lists"
            )
            if result_idx is not None:
                ui_manager.selected_list_idx = result_idx
                app_state.preview_list_id = app_state.task_lists[result_idx]["id"]
                ui_manager.selected_task_idx = 0
            return True

    # List reordering (only in lists panel)
    if ui_manager.active_panel == "lists" and app_state.task_lists:
        if key == ord(","):
            app_state.move_list_down(ui_manager.selected_list_idx, ui_manager)
            return True
        elif key == ord("."):
            app_state.move_list_up(ui_manager.selected_list_idx, ui_manager)
            return True
        elif key == ord("s"):
            app_state.reset_list_order()
            ui_manager.show_temporary_message("List order reset to original")
            return True

    # Action Keys

    if key == ord("c"):
        # Toggle task status
        if ui_manager.active_panel == "tasks" and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            app_state.service.toggle_task_status(
                app_state.active_list_id, selected_task["id"]
            )
            app_state.refresh_data()  # Refresh display after change

    elif key == ord("w"):
        ui_manager.start_sync_animation()
        app_state.service.sync_to_google()
        ui_manager.stop_sync_animation()
        app_state.refresh_data()

    elif key == ord("r"):
        if ui_manager.active_panel == "tasks" and app_state.tasks:
            new_title = ui_manager.get_user_input("New Task Title: ")
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            app_state.service.rename_task(
                app_state.active_list_id, selected_task["id"], new_title
            )
            app_state.refresh_data()  # Refresh display after change
        elif ui_manager.active_panel == "lists" and app_state.task_lists:
            new_title = ui_manager.get_user_input("New List Title: ")
            if new_title:
                selected_list = app_state.task_lists[ui_manager.selected_list_idx]
                app_state.service.rename_list(selected_list["id"], new_title)
                app_state.refresh_data()

    elif key == ord("a"):
        if ui_manager.active_panel == "tasks" and app_state.tasks:
            new_date = ui_manager.get_user_input("Due Date: ")
            if is_valid_date(new_date):
                selected_task = app_state.tasks[ui_manager.selected_task_idx]
                app_state.service.change_date_task(
                    app_state.active_list_id, selected_task["id"], new_date
                )
                app_state.refresh_data()
            else:
                ui_manager.show_temporary_message(f"Invalid date format: '{new_date}'")

    elif key == ord("i"):
        if ui_manager.active_panel == "tasks" and app_state.tasks:
            open_editor_for_task_notes(stdscr, app_state, ui_manager)

    elif key == ord("d"):
        if ui_manager.active_panel == "tasks" and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            app_state.task_buffer = app_state.service.get_task(
                app_state.active_list_id, selected_task["id"]
            )
            app_state.service.delete_task(app_state.active_list_id, selected_task["id"])
            app_state.refresh_data()  # Refresh display after change
            # Adjust selection after deletion
            if (
                ui_manager.selected_task_idx >= len(app_state.tasks)
                and len(app_state.tasks) > 0
            ):
                ui_manager.selected_task_idx = len(app_state.tasks) - 1
        elif ui_manager.active_panel == "lists" and app_state.task_lists:
            selected_list = app_state.task_lists[ui_manager.selected_list_idx]
            confirm = ui_manager.get_user_input(
                f"Delete list '{selected_list['title']}'? (y/n): "
            )
            if confirm.lower() == "y":
                app_state.list_buffer = selected_list["title"]
                list_id_to_delete = selected_list["id"]
                app_state.service.delete_list(list_id_to_delete)
                # Remove from list_order to keep it clean
                if list_id_to_delete in app_state.list_order:
                    app_state.list_order.remove(list_id_to_delete)
                    app_state.service.set_list_order(app_state.list_order)
                app_state.task_lists = app_state.service.get_task_lists(
                    app_state.list_order
                )
                if app_state.task_lists:
                    app_state.change_active_list(app_state.task_lists[0]["id"])
                else:
                    app_state.active_list_id = None
                app_state.refresh_data()

    elif key == ord("p"):
        if ui_manager.active_panel == "tasks":
            if app_state.tasks:
                current_task = app_state.tasks[ui_manager.selected_task_idx]
                unfiltered_tasks = app_state.service.data["tasks"][
                    app_state.active_list_id
                ]
                unfiltered_index = -1
                for i, task in enumerate(unfiltered_tasks):
                    if task["id"] == current_task["id"]:
                        unfiltered_index = i
                        break

                if unfiltered_index != -1:
                    app_state.service.add_task_body(
                        app_state.active_list_id,
                        app_state.task_buffer,
                        unfiltered_index,
                    )
                else:
                    # Should not happen, but as a fallback, append to the end
                    app_state.service.add_task_body(
                        app_state.active_list_id, app_state.task_buffer
                    )
            else:
                # Pasting into an empty list
                app_state.service.add_task_body(
                    app_state.active_list_id, app_state.task_buffer
                )
            app_state.refresh_data()
        else:
            # Paste list - create from buffer and select it
            new_list = app_state.service.add_list(app_state.list_buffer)
            # Add to list_order for proper ordering
            app_state.list_order.append(new_list["id"])
            app_state.service.set_list_order(app_state.list_order)
            app_state.refresh_data()
            # Select the newly created list
            for i, lst in enumerate(app_state.task_lists):
                if lst["id"] == new_list["id"]:
                    ui_manager.selected_list_idx = i
                    app_state.preview_list_id = new_list["id"]
                    break

    # Add New Task
    elif key == ord("o"):
        if ui_manager.active_panel == "tasks":
            new_title = ui_manager.get_user_input("New Task Title: ")
            if new_title:
                if app_state.current_parent_task_id:
                    app_state.service.add_task(
                        app_state.active_list_id,
                        new_title,
                        parent=app_state.current_parent_task_id,
                    )
                else:
                    app_state.service.add_task(app_state.active_list_id, new_title)
                app_state.refresh_data()  # Fetch and display the new task
        else:
            new_title = ui_manager.get_user_input("New List Title: ")
            if new_title:
                new_list = app_state.service.add_list(new_title)
                # Add to list_order for proper ordering
                app_state.list_order.append(new_list["id"])
                app_state.service.set_list_order(app_state.list_order)
                app_state.refresh_data()
                # Select the newly created list
                for i, lst in enumerate(app_state.task_lists):
                    if lst["id"] == new_list["id"]:
                        ui_manager.selected_list_idx = i
                        app_state.preview_list_id = new_list["id"]
                        break

    elif key == ord("?"):
        ui_manager.toggle_help()

    elif key == ord("f"):
        app_state.hide_completed = not app_state.hide_completed
        ui_manager.hide_completed = app_state.hide_completed
        app_state.tasks = app_state.get_tasks_for_active_list()
        if (
            ui_manager.selected_task_idx >= len(app_state.tasks)
            and len(app_state.tasks) > 0
        ):
            ui_manager.selected_task_idx = len(app_state.tasks) - 1
        app_state.save_config()

    elif key == ord("m"):
        if ui_manager.active_panel == "tasks" and app_state.tasks:
            target_list_id = ui_manager.show_list_selector(
                app_state.task_lists, app_state.active_list_id
            )
            if target_list_id:
                selected_task = app_state.tasks[ui_manager.selected_task_idx]
                app_state.service.move_task(
                    app_state.active_list_id,
                    target_list_id,
                    selected_task["id"],
                )
                app_state.refresh_data()
                target_list_title = next(
                    (
                        lst["title"]
                        for lst in app_state.task_lists
                        if lst["id"] == target_list_id
                    ),
                    "unknown",
                )
                ui_manager.show_temporary_message(f"Moved to '{target_list_title}'")

    return True  # Keep the loop running


def main_loop(stdscr):
    """The main application loop function required by curses.wrapper."""
    # 1. Initialization
    task_service = TaskService()
    ui_manager = UIManager(stdscr)
    app_state = AppState(task_service)

    # Disable cursor visibility for a cleaner TUI
    curs_set(0)
    noecho()
    cbreak()
    keypad(stdscr, True)

    ui_manager.start_sync_animation()
    app_state.service.sync_from_google()
    ui_manager.stop_sync_animation()
    app_state.refresh_data()

    running = True
    while running:
        # 2. Draw the UI based on current state
        try:
            # Determine which list to show: preview (when in lists panel) or active
            display_list_id = app_state.active_list_id
            display_tasks = app_state.tasks
            is_preview = False

            if ui_manager.active_panel == "lists" and app_state.preview_list_id:
                display_list_id = app_state.preview_list_id
                display_tasks = app_state.get_preview_tasks(display_list_id)
                is_preview = True

            parent_task = None
            if app_state.current_parent_task_id:
                parent_task = app_state.service.get_task(
                    app_state.active_list_id, app_state.current_parent_task_id
                )

            parent_ids = app_state.service.get_parent_task_ids(display_list_id)
            children_counts = app_state.service.get_children_counts(display_list_id)

            # Get subtasks for selected task (for bottom panel)
            selected_task = None
            subtasks = []
            if (
                ui_manager.active_panel == "tasks"
                and display_tasks
                and ui_manager.selected_task_idx < len(display_tasks)
            ):
                selected_task = display_tasks[ui_manager.selected_task_idx]
                if selected_task:
                    if selected_task.get("id") in parent_ids:
                        subtasks = app_state.service.get_subtasks(
                            display_list_id, selected_task["id"]
                        )

            ui_manager.draw_layout(
                app_state.task_lists,
                display_tasks,
                app_state.active_list_id,
                app_state.task_counts,
                parent_task=parent_task,
                parent_ids=parent_ids,
                children_counts=children_counts,
                hide_completed=app_state.hide_completed,
                selected_task=selected_task,
                subtasks=subtasks,
                preview_list_id=display_list_id if is_preview else None,
            )
        except Exception as e:
            # Handles window resize errors gracefully
            ui_manager.show_temporary_message(f"Error: {e}")

        # 3. Handle User Input
        running = handle_input(stdscr, app_state, ui_manager)


def cli():
    try:
        wrapper(main_loop)
    except Exception as e:
        # Print the error before exiting the terminal session
        print(f"An error occurred: {e}", file=sys.stderr)


if __name__ == "__main__":
    cli()
