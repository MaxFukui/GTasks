# Textual UI — Architecture & Implementation Plan

## Context

This is a rewrite of the UI layer of GTasks (a Google Tasks TUI app) using the
`textual` library. The existing unicurses version lives on the `main` branch and
must not be touched. This branch (`feature/textual-ui`) is the development sandbox.

The data layer is already clean and must be reused as-is:
- `tasks_tui/local_storage.py` — JSON persistence, no changes needed
- `tasks_tui/task_service.py` — Google API + local cache, no changes needed

Only the UI layer is being replaced.

---

## What Textual is and why it matters

Textual is a reactive TUI framework. Instead of manually redrawing the screen after
every action (like the unicurses version does), you:
1. Declare widgets and their layout
2. Hold state as `reactive` attributes on the App or widgets
3. Textual automatically re-renders anything that depends on changed state

This means `AppState` (the god-object in main.py) should not be ported. Instead,
state should live as reactive attributes on the App class.

---

## Target folder structure

```
tasks_tui/
├── local_storage.py          # UNTOUCHED
├── task_service.py           # UNTOUCHED
├── main.py                   # UNTOUCHED (unicurses entry point)
│
└── textual_ui/
    ├── __init__.py
    ├── app.py                # Textual App class + top-level reactive state
    ├── screens/
    │   └── main_screen.py    # Main screen: composes the three panels
    └── widgets/
        ├── list_panel.py     # Left panel — task lists
        ├── task_panel.py     # Right panel — tasks for active list
        └── subtask_panel.py  # Bottom panel — subtasks for selected task
```

Add a second entry point to `pyproject.toml`:
```toml
tasks-tui-textual = "tasks_tui.textual_ui.app:cli"
```

This lets both UIs coexist and be tested side by side during development.

---

## State management rules

The App class (`app.py`) owns all reactive state:
- `active_list_id: reactive[str]` — which list is currently open
- `selected_task_id: reactive[str | None]` — which task is highlighted
- `hide_completed: reactive[bool]` — filter toggle

Widgets do NOT hold state themselves. They receive data via the App's reactive
attributes and post messages (Textual's event system) upward when the user acts.

The `task_service.TaskService` instance lives on the App and is accessed by widgets
via `self.app.service`.

---

## Widget responsibilities

### ListPanel (left)
- Displays all task lists from `service.get_task_lists()`
- Highlights the active list
- Posts `ListSelected(list_id)` message on selection
- Posts `ListReorderRequested(list_id, direction)` for reordering

### TaskPanel (right)
- Displays tasks for `app.active_list_id`
- Reacts to `active_list_id` changes automatically
- Posts `TaskSelected(task_id)` on highlight change
- Posts `TaskActionRequested(action, task_id)` for toggle/delete/rename/etc.

### SubtaskPanel (bottom)
- Only visible when selected task has children
- Reacts to `selected_task_id` changes
- Displays subtasks read-only (for now)

---

## Sync strategy

Keep the same explicit sync model as the unicurses version:
- All edits are local-only (dirty flag)
- Sync to Google only on `w` (write) or `q` (quit with dirty=True)
- Show a loading indicator (Textual has `LoadingIndicator` built in) during sync

Do NOT add auto-sync or background polling. This was a deliberate design decision.

---

## Key Textual APIs to use

- `textual.app.App` — base class, define `CSS`, `BINDINGS`, `compose()`
- `textual.reactive.reactive` — reactive state attributes
- `textual.widgets.ListView` + `ListItem` — good fit for lists and task panels
- `textual.widgets.Footer` — auto-renders keybindings from `BINDINGS`
- `textual.widgets.Header` — top bar with app title
- `textual.on` decorator — handle messages from child widgets
- `app.push_screen` / `app.pop_screen` — for modal dialogs (rename, date input)

---

## Implementation order (suggested)

1. Scaffold `textual_ui/` folder, create empty files, add entry point to pyproject.toml
2. Build `app.py` with `TaskService` init, reactive state, basic layout shell
3. Build `ListPanel` — static display first, then selection interaction
4. Build `TaskPanel` — display tasks, react to active list changes
5. Wire up actions: toggle complete, add task, rename, delete
6. Build `SubtaskPanel` — display only first, interaction later
7. Add modal screens for text input (rename, new task, due date)
8. Add sync (`w` and `q` bindings) with loading indicator
9. Polish: CSS styling, keybinding footer, help screen
