# list_panel.py - Left panel showing task lists
from textual.widgets import ListView, ListItem
from textual.message import Message
from textual.reactive import reactive


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

    active_list_id = reactive[str | None](None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "list-panel"

    def watch_active_list_id(self, active_list_id: str | None):
        """React to active list changes."""
        self.refresh_list_items()

    def on_mount(self):
        """Called when widget is mounted."""
        self.refresh_list_items()

    def refresh_list_items(self):
        """Refresh the list items from the service."""
        self.clear()

        service = self.app.service
        lists = service.get_task_lists()

        for lst in lists:
            list_id = lst.get("id", "")
            title = lst.get("title", "Untitled")
            task_count = len(service.get_tasks_for_list(list_id))

            # Mark active list
            display_title = f"{title} ({task_count})"

            item = ListItem(
                Text(display_title, markup=False),
                id=list_id,
            )

            if list_id == self.active_list_id:
                item.add_class("active-list")

            self.append(item)

    def on_list_view_selected(self, event):
        """Handle list item selection."""
        list_id = event.item.id
        if list_id:
            self.post_message(ListSelected(list_id))


from textual.widgets import Static


class Text(Static):
    """Simple text widget for list items."""

    pass
