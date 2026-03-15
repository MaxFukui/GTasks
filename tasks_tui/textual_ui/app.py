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
    Screen {
        layout: vertical;
    }

    # main-panels {
        layout: horizontal;
        height: 1fr;
    }

    # list-panel {
        width: 25%;
        border: solid $surface;
    }

    # task-panel {
        width: 75%;
        border: solid $surface;
    }

    # subtask-panel {
        height: auto;
        max-height: 8;
        border: solid $accent;
    }

    ListView {
        height: 100%;
    }

    ListItem {
        padding: 0 1;
    }

    .active-list {
        text-style: bold;
    }

    .completed-task {
        color: $text-muted;
        text-style: dim;
    }
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
        pass

    def action_rename(self):
        pass

    def action_delete(self):
        pass

    def action_toggle_complete(self):
        pass

    def action_set_due_date(self):
        pass

    def action_paste(self):
        pass

    def action_move_task(self):
        pass


def cli():
    """Entry point for the Textual UI."""
    app = GTasksApp()
    app.run()
