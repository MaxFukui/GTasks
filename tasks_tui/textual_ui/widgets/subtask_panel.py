# subtask_panel.py - Bottom panel showing subtasks for selected task
from textual.widgets import ListView, ListItem, Static
from textual.reactive import reactive
from dateutil.parser import isoparse


class SubtaskPanel(ListView):
    """Panel displaying subtasks for selected task."""

    selected_task_id = reactive[str | None](None)
    active_list_id = reactive[str | None](None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "subtask-panel"
        self.visible = False

    def watch_selected_task_id(self, selected_task_id: str | None):
        """React to selected task changes."""
        self.refresh_subtask_items()

    def watch_active_list_id(self, active_list_id: str | None):
        """React to active list changes."""
        self.refresh_subtask_items()

    def on_mount(self):
        """Called when widget is mounted."""
        self.refresh_subtask_items()

    def refresh_subtask_items(self):
        """Refresh subtask items from service."""
        self.clear()

        if not self.selected_task_id or not self.active_list_id:
            self.visible = False
            return

        service = self.app.service

        # Check if task has children
        parent_ids = service.get_parent_task_ids(self.active_list_id)
        if self.selected_task_id not in parent_ids:
            self.visible = False
            return

        # Get subtasks
        subtasks = service.get_subtasks(self.active_list_id, self.selected_task_id)

        if not subtasks:
            self.visible = False
            return

        self.visible = True

        for task in subtasks:
            task_id = task.get("id", "")
            title = task.get("title", "Untitled")
            status = task.get("status", "needsAction")

            # Build display string
            symbol = "✓" if status == "completed" else "○"

            # Due date
            due_str = ""
            if task.get("due"):
                try:
                    due_date = isoparse(task["due"])
                    due_str = f" {due_date.strftime('%m/%d')}"
                except ValueError:
                    pass

            display = f"  {symbol} {title}{due_str}"

            item = ListItem(
                Static(display, markup=False),
                id=task_id,
            )

            if status == "completed":
                item.add_class("completed-task")

            self.append(item)
