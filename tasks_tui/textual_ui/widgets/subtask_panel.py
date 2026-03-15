# subtask_panel.py - Bottom panel showing subtasks for selected task
from textual.widgets import ListView, ListItem, Static
from dateutil.parser import isoparse


class SubtaskPanel(ListView):
    """Panel displaying subtasks for selected task."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "subtask-panel"
        self.display = False  # Start hidden

    def refresh_subtask_items(self):
        """Refresh subtask items from service."""
        self.clear()

        selected_task_id = self.app.selected_task_id
        active_list_id = self.app.active_list_id

        if not selected_task_id or not active_list_id:
            self.display = False
            return

        service = self.app.service

        # Check if task has children
        parent_ids = service.get_parent_task_ids(active_list_id)
        if selected_task_id not in parent_ids:
            self.display = False
            return

        # Get subtasks
        subtasks = service.get_subtasks(active_list_id, selected_task_id)

        if not subtasks:
            self.display = False
            return

        self.display = True

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
