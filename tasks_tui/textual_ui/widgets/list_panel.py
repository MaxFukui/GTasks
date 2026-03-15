# list_panel.py - Left panel showing task lists
from textual.widgets import ListView, ListItem, Static
from textual.message import Message


class ListSelected(Message):
    """Message posted when a list is selected."""

    def __init__(self, list_id: str):
        self.list_id = list_id
        super().__init__()


class ListReorderRequested(Message):
    """Message posted when list reordering is requested."""

    def __init__(self, list_id: str, direction: str):
        self.list_id = list_id
        self.direction = direction  # "up" or "down"
        super().__init__()


class ListPanel(ListView):
    """Panel displaying all task lists."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "list-panel"

    def on_mount(self):
        """Called when widget is mounted."""
        self.refresh_list_items()

    def refresh_list_items(self):
        """Refresh the list items from the service."""
        self.clear()

        service = self.app.service
        lists = service.get_task_lists()
        active_list_id = self.app.active_list_id

        for lst in lists:
            list_id = lst.get("id", "")
            title = lst.get("title", "Untitled")
            task_count = len(service.get_tasks_for_list(list_id))

            # Mark active list
            display_title = f"{title} ({task_count})"

            item = ListItem(
                Static(display_title, markup=False),
                id=list_id,
            )

            if list_id == active_list_id:
                item.add_class("active-list")

            self.append(item)

    def on_list_view_selected(self, event):
        """Handle list item selection."""
        list_id = event.item.id
        if list_id:
            self.post_message(ListSelected(list_id))
