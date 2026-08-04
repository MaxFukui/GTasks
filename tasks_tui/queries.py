"""Pure query helpers over the local Google Tasks cache.

Every function takes the raw cache dict (the shape local_storage.load_data()
returns) and returns plain data. No credentials, no network, no curses — this
is the module the CLI path uses so a query costs nothing but a JSON read.

TaskService delegates its read methods here, so these functions are the single
definition of what "the tasks in a list" means for both the TUI and the CLI.
"""

STAR_MARKER = "⭐"


def is_starred(task):
    """Returns True if the task title starts with the star marker."""
    return task.get("title", "").startswith(STAR_MARKER)


def display_title(task):
    """Returns the task title with the star marker stripped."""
    title = task.get("title", "")
    return title[len(STAR_MARKER):] if title.startswith(STAR_MARKER) else title


def task_lists(data, list_order=None):
    """All non-deleted task lists, optionally sorted by an explicit id order.

    Lists whose id is absent from list_order sort to the end.
    """
    lists = [lst for lst in data.get("task_lists", []) if not lst.get("deleted")]

    if list_order:

        def sort_key(lst):
            lst_id = lst.get("id", "")
            if lst_id in list_order:
                return list_order.index(lst_id)
            return len(list_order)

        lists.sort(key=sort_key)

    return lists


def tasks_for_list(data, list_id):
    """Top-level (non-subtask), non-deleted tasks in one list.

    Completed tasks are included — filtering those is the caller's choice,
    via without_completed().
    """
    if not list_id:
        return []
    return [
        task
        for task in data.get("tasks", {}).get(list_id, [])
        if not task.get("deleted") and not task.get("parent")
    ]


def subtasks(data, list_id, parent_task_id):
    """Non-deleted direct children of one task."""
    if not list_id or not parent_task_id:
        return []
    return [
        task
        for task in data.get("tasks", {}).get(list_id, [])
        if not task.get("deleted") and task.get("parent") == parent_task_id
    ]


def all_tasks_for_list(data, list_id):
    """Every non-deleted task in one list, subtasks included."""
    if not list_id:
        return []
    return [
        task
        for task in data.get("tasks", {}).get(list_id, [])
        if not task.get("deleted")
    ]


def starred_tasks(data):
    """(list_id, task) for every non-deleted, top-level starred task."""
    starred = []
    for list_id, tasks in data.get("tasks", {}).items():
        for task in tasks:
            if (
                not task.get("deleted")
                and not task.get("parent")
                and is_starred(task)
            ):
                starred.append((list_id, task))
    return starred


def without_completed(tasks):
    """Drops completed tasks. Used by the CLI, which hides them by default."""
    return [task for task in tasks if task.get("status") != "completed"]
