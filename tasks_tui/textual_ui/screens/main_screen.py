# main_screen.py - Main screen composing all panels
from textual.screen import Screen
from textual.containers import Horizontal, Vertical
from textual import on

from tasks_tui.textual_ui.widgets.list_panel import ListPanel, ListSelected
from tasks_tui.textual_ui.widgets.task_panel import TaskPanel, TaskSelected
from tasks_tui.textual_ui.widgets.subtask_panel import SubtaskPanel


class MainScreen(Screen):
    """Main screen with three-panel layout."""

    BINDINGS = [
        ("h", "focus_left", "Left"),
        ("l", "focus_right", "Right"),
        ("j", "focus_down", "Down"),
        ("k", "focus_up", "Up"),
    ]

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
        # Focus the list panel by default
        self.list_panel.focus()

    def on_list_selected(self, event: ListSelected):
        """Handle list selection."""
        self.app.active_list_id = event.list_id
        self.task_panel.refresh_task_items()
        self.subtask_panel.refresh_subtask_items()
        self.save_config()

    def on_task_selected(self, event: TaskSelected):
        """Handle task selection."""
        self.app.selected_task_id = event.task_id
        self.subtask_panel.refresh_subtask_items()

    def action_focus_left(self):
        """Move focus to the left panel."""
        self.list_panel.focus()

    def action_focus_right(self):
        """Move focus to the right panel."""
        self.task_panel.focus()

    def action_focus_down(self):
        """Move focus down in current panel."""
        self.focused.scroll_down()

    def action_focus_up(self):
        """Move focus up in current panel."""
        self.focused.scroll_up()

    def save_config(self):
        """Save configuration."""
        from tasks_tui import local_storage

        config = {
            "hide_completed": self.app.hide_completed,
            "active_list_id": self.app.active_list_id,
            "list_order": getattr(self.app.service, "list_order", []),
        }
        local_storage.save_config(config)
