# GTasks TUI - Developer Documentation

## Project Overview

GTasks TUI is a terminal-based user interface for Google Tasks, allowing users to manage their Google Tasks directly from the command line using a curses-based interface.

## Project Structure

```
GTasks/
├── tasks_tui/              # Main package
│   ├── __init__.py        # Package marker
│   ├── main.py            # Entry point / Controller layer
│   ├── ui_manager.py     # View layer (curses UI rendering)
│   ├── task_service.py   # Model layer (API + local cache)
│   ├── auth.py           # Google OAuth authentication
│   └── local_storage.py  # Local JSON file persistence
├── pyproject.toml         # Project metadata & dependencies
├── requirements.txt       # pip dependencies
├── README.md              # User documentation
└── LICENSE                # MIT license
```

## Tech Stack

- **Language**: Python 3
- **TUI Library**: uni-curses (curses wrapper for cross-platform terminal UI)
- **Google API**: google-api-python-client (tasks v1 API)
- **Authentication**: google-auth-oauthlib
- **Date Handling**: python-dateutil
- **Storage**: Local JSON files in `~/.gtask/`

## Architecture

The application follows the **MVC (Model-View-Controller)** pattern:

1. **Model** (`task_service.py`): Handles Google Tasks API communication, local caching, and data manipulation. Uses a dirty flag to track unsynced changes.

2. **View** (`ui_manager.py`): Handles all curses-based screen drawing, window management, colors, and user input prompts.

3. **Controller** (`main.py`): Manages the application state (AppState class), event loop, and input handling. Coordinates between Model and View.

### Data Flow
```
Google Tasks API <--sync--> TaskService (Model) <--> Local JSON Cache
                           |
                           v
                      AppState (Controller)
                           |
                           v
                      UIManager (View) <--input-- Terminal
```

## Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit application (syncs on exit if dirty) |
| `w` | Manual sync with Google |
| `↑/k` | Move selection up |
| `↓/j` | Move selection down |
| `←/h` | Go back / Switch to lists panel |
| `→/l` | Enter task list / Enter subtask |
| `o` | Create new task (in tasks panel) or new list (in lists panel) |
| `d` | Delete selected task or list |
| `r` | Rename selected task or list |
| `c` | Toggle task completion status |
| `a` | Add/change due date |
| `i` | Edit task notes (opens external editor) |
| `p` | Paste task from buffer |
| `?` | Toggle help overlay |

## Coding Conventions

### General Style
- Uses snake_case for variables and functions
- No type hints present in the codebase
- Comments at file headers explain the layer/role
- Docstrings on some functions but inconsistent

### Class Organization
- `TaskService`: Central data manager, handles all API and cache operations
- `UIManager`: Handles all UI rendering and input collection
- `AppState`: Simple container for application state (no methods beyond init/refresh)

### Key Patterns
- **Dirty Flag**: `self.dirty` tracks unsynced local changes
- **Temp IDs**: Newly created items use `temp_` prefixed IDs until synced
- **Caching**: Uses `filtered_tasks_cache` to avoid repeated API calls
- **Panel System**: Tracks `active_panel` ('lists' or 'tasks') for navigation

### Error Handling
- Minimal error handling; many operations silently fail
- Uses try/except in `handle_input` for curses errors
- Network errors during sync are caught but not surfaced meaningfully

## Potential Improvements

### High Priority
1. **Add Type Hints**: Throughout codebase for better maintainability
2. **Add Error Handling**: Surface API errors, network failures, and invalid input to users
3. **Add Tests**: No test suite exists; critical for refactoring
4. **Fix Window Resize**: Currently can crash; needs robust resize handling

### Medium Priority
5. **Search/Filter**: No way to filter tasks by text or status
6. **Task Sorting**: No control over task ordering
7. **Recurrence**: Google Tasks supports recurring tasks; not exposed
8. **Configuration File**: No way to customize keybindings, editor, or sync behavior
9. **Batch Operations**: Cannot select multiple tasks for bulk actions
10. **Offline Mode**: Works but sync failures are not well-handled

### Low Priority
11. **Breadcrumb Navigation**: When in subtasks, no indicator of parent path
12. **Custom Keybindings**: Users cannot remap keys
13. **Logging**: No logging infrastructure for debugging
14. **Task Prioritization**: No support for Google Tasks "priority" field
15. **List Colors/Labels**: Google supports labels; not exposed
16. **Completion Progress**: Show completion percentage per list
17. **Due Date Notifications**: No alerts for upcoming due dates
18. **Task Moving**: No UI to move tasks between lists
19. **Undo Functionality**: No undo for delete/rename operations
20. **Pagination**: Assumes all tasks fit on screen; no scrolling for long lists

### Code Quality
21. **Extract Constants**: Magic strings (e.g., "temp_", "needsAction") should be constants
22. **Input Validation**: `get_user_input` returns empty strings unchecked
23. **Memory**: Holds all tasks in memory; could use streaming for large lists
24. **Thread Safety**: Animation thread and main thread share state without locks
