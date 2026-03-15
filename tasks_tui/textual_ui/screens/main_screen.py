# main_screen.py - Main screen composing all panels
from textual.screen import Screen
from textual.containers import Horizontal, Vertical

from tasks_tui.textual_ui.widgets.list_panel import ListPanel, ListSelected
from tasks_tui.textual_ui.widgets.task_panel import TaskPanel, TaskSelected
from tasks_tui.textual_ui.widgets.subtask_panel import SubtaskPanel


class MainScreen(Screen):
    """Main screen with three-panel layout."""

    def __init__(self):
        super().__init__()
        self.list_panel = ListPanel()
        self.task_panel = TaskPanel()
        self.subtask_panel = SubtaskPanel()

    def compose(self):
        """Create the layout."""
        # Top section: list and task panels side by side
        top_section = Horizontal(self.list_panel, self.task_panel)

        yield top_section
        yield self.subtask_panel

    def on_mount(self):
        """Called when screen is mounted."""
        # Set initial reactive values from app
        app = self.app
        self.list_panel.active_list_id = app.active_list_id
        self.task_panel.active_list_id = app.active_list_id
        self.task_panel.hide_completed = app.hide_completed
        self.subtask_panel.active_list_id = app.active_list_id
        self.subtask_panel.selected_task_id = app.selected_task_id

    def on_list_selected(self, event: ListSelected):
        """Handle list selection."""
        self.app.active_list_id = event.list_id
        self.task_panel.active_list_id = event.list_id
        self.subtask_panel.active_list_id = event.list_id
        # Save config
        self.save_config()

    def on_task_selected(self, event: TaskSelected):
        """Handle task selection."""
        self.app.selected_task_id = event.task_id
        self.subtask_panel.selected_task_id = event.task_id

    def save_config(self):
        """Save configuration."""
        from tasks_tui import local_storage

        config = {
            "hide_completed": self.app.hide_completed,
            "active_list_id": self.app.active_list_id,
            "list_order": getattr(self.app.service, "list_order", []),
        }
        local_storage.save_config(config)

    def watch_app_active_list_id(self, active_list_id):
        """React to active list changes from app."""
        self.list_panel.active_list_id = active_list_id
        self.task_panel.active_list_id = active_list_id
        self.subtask_panel.active_list_id = active_list_id

    def watch_app_hide_completed(self, hide_completed):
        """React to hide_completed changes from app."""
        self.task_panel.hide_completed = hide_completed
        self.task_panel.refresh_task_items()
