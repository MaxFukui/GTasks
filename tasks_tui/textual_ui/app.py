# app.py - Textual App class and top-level state
from textual.app import App
from textual.reactive import reactive
from textual import on
from textual.widgets import Header, Footer

from tasks_tui.task_service import TaskService
from tasks_tui import local_storage

from .screens.main_screen import MainScreen


class GTasksApp(App):
    """Textual-based GTasks application."""

    CSS = """
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("w", "sync", "Sync"),
        ("o", "new_item", "New"),
        ("r", "rename", "Rename"),
        ("d", "delete", "Delete"),
        ("c", "toggle_complete", "Toggle"),
        ("a", "set_due_date", "Due Date"),
        ("p", "paste", "Paste"),
        ("f", "toggle_hide_completed", "Hide Done"),
        ("m", "move_task", "Move"),
        ("?", "toggle_help", "Help"),
        ("tab", "focus_next", "Next Panel"),
        ("shift+tab", "focus_previous", "Prev Panel"),
    ]

    # Reactive state
    active_list_id = reactive[str | None](None)
    selected_task_id = reactive[str | None](None)
    hide_completed = reactive[bool](False)

    def __init__(self):
        super().__init__()
        self.service = TaskService()

        # Load config
        config = local_storage.load_config()
        self.hide_completed = config.get("hide_completed", False)

        # Set initial active list
        if config.get("active_list_id"):
            self.active_list_id = config.get("active_list_id")
        else:
            lists = self.service.get_task_lists()
            if lists:
                self.active_list_id = lists[0]["id"]

    def on_mount(self):
        """Called when app is mounted."""
        self.push_screen(MainScreen())

    def action_quit(self):
        """Quit the application, syncing if dirty."""
        if self.service.dirty:
            self.service.sync_to_google()
        self.exit()

    def action_sync(self):
        """Sync with Google."""
        self.service.sync_to_google()
        self.refresh()

    def action_toggle_hide_completed(self):
        """Toggle hiding completed tasks."""
        self.hide_completed = not self.hide_completed

        # Refresh the task panel
        screen = self.screen
        if hasattr(screen, "task_panel"):
            screen.task_panel.refresh_task_items()

        # Save config
        config = {
            "hide_completed": self.hide_completed,
            "active_list_id": self.active_list_id,
            "list_order": getattr(self.service, "list_order", []),
        }
        local_storage.save_config(config)

    def action_toggle_help(self):
        """Toggle help overlay."""
        pass  # TODO: Implement help screen

    def action_focus_next(self):
        """Move focus to next panel."""
        pass  # TODO: Implement panel navigation

    def action_focus_previous(self):
        """Move focus to previous panel."""
        pass  # TODO: Implement panel navigation

    # Action placeholders - to be implemented
    def action_new_item(self):
        """Create new task or list based on focused panel."""
        screen = self.screen
        if not hasattr(screen, "list_panel") or not hasattr(screen, "task_panel"):
            return

        if screen.list_panel.has_focus:
            # Create new list - use Input dialog (placeholder for now)
            # For now, just add a new list with a default name
            new_list = self.service.add_list("New List")
            screen.list_panel.refresh_list_items()
        elif screen.task_panel.has_focus:
            # Create new task
            if self.active_list_id:
                new_task = self.service.add_task(self.active_list_id, "New Task")
                screen.task_panel.refresh_task_items()

    def action_rename(self):
        pass

    def action_toggle_complete(self):
        """Toggle task completion status."""
        screen = self.screen
        if not hasattr(screen, "task_panel"):
            return

        task_panel = screen.task_panel
        if task_panel.index is None:
            return

        tasks = task_panel.items
        if task_panel.index >= len(tasks):
            return

        task_id = task_panel.index[task_panel.index].id

        self.service.toggle_task_status(self.active_list_id, task_id)
        task_panel.refresh_task_items()

    def action_delete(self):
        """Delete selected task or list."""
        screen = self.screen
        if not hasattr(screen, "list_panel") or not hasattr(screen, "task_panel"):
            return

        # Check if we're in list or task panel
        if screen.list_panel.has_focus:
            # Delete list
            list_panel = screen.list_panel
            if list_panel.index is None:
                return

            list_id = list_panel.index[list_panel.index].id
            if list_id:
                self.service.delete_list(list_id)
                screen.list_panel.refresh_list_items()
        elif screen.task_panel.has_focus:
            # Delete task
            task_panel = screen.task_panel
            if task_panel.index is None:
                return

            task_id = task_panel.index[task_panel.index].id
            if task_id:
                self.service.delete_task(self.active_list_id, task_id)
                task_panel.refresh_task_items()

    def action_set_due_date(self):
        """Set due date for selected task (placeholder)."""
        pass

    def action_paste(self):
        """Paste task/list (placeholder)."""
        pass

    def action_move_task(self):
        """Move task to another list (placeholder)."""
        pass


def cli():
    """Entry point for the Textual UI."""
    app = GTasksApp()
    app.run()
