# task_panel.py - Right panel showing tasks for active list
from textual.widgets import ListView, ListItem, Static
from textual.message import Message
from dateutil.parser import isoparse


class TaskSelected(Message):
    """Message posted when a task is selected."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__()


class TaskActionRequested(Message):
    """Message posted when a task action is requested."""

    def __init__(self, action: str, task_id: str):
        self.action = action
        self.task_id = task_id
        super().__init__()


class TaskPanel(ListView):
    """Panel displaying tasks for the active list."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "task-panel"

    def on_mount(self):
        """Called when widget is mounted."""
        self.refresh_task_items()

    def refresh_task_items(self):
        """Refresh the task items from the service."""
        self.clear()

        active_list_id = self.app.active_list_id
        if not active_list_id:
            return

        service = self.app.service
        tasks = service.get_tasks_for_list(active_list_id)

        # Filter completed if hide_completed is True
        if self.app.hide_completed:
            tasks = [t for t in tasks if t.get("status") != "completed"]

        # Get parent task IDs and children counts
        parent_ids = service.get_parent_task_ids(active_list_id)
        children_counts = service.get_children_counts(active_list_id)

        for task in tasks:
            task_id = task.get("id", "")
            title = task.get("title", "Untitled")
            status = task.get("status", "needsAction")

            # Build display string
            symbol = "✓" if status == "completed" else "○"

            # Note indicator
            note = "📝" if task.get("notes") else ""

            # Due date
            due_str = ""
            if task.get("due"):
                try:
                    due_date = isoparse(task["due"])
                    due_str = f" {due_date.strftime('%m/%d')}"
                except ValueError:
                    pass

            # Children indicator
            children_count = children_counts.get(task_id, 0)
            children_str = f" ⤵{children_count}" if children_count > 0 else ""

            display = f"{symbol} {note}{title}{due_str}{children_str}"

            item = ListItem(
                Static(display, markup=False),
                id=task_id,
            )

            if status == "completed":
                item.add_class("completed-task")

            self.append(item)

    def on_list_view_selected(self, event):
        """Handle task selection."""
        task_id = event.item.id
        if task_id:
            self.post_message(TaskSelected(task_id))
