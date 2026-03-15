# UI Design — Textual Version

## Layout concept

The goal is a clean three-panel layout that feels native to the terminal, uses
Textual's CSS grid properly, and is more visually polished than the unicurses version.

```
┌─────────────────────────────────────────────────────────────────────┐
│  GTasks                                            15 Mar 2026      │  ← Header
├──────────────────┬──────────────────────────────────────────────────┤
│                  │                                                   │
│  LISTS           │  TASKS — Work                                    │
│  ─────────────   │  ───────────────────────────────────────────     │
│  > Work    (5)   │  ○  Write project proposal          03/20        │
│    Personal (3)  │  ○  📝 Review pull requests                      │
│    Shopping (8)  │  ✓  Update dependencies             ⤵3          │
│    Ideas   (2)   │  ○  Fix login bug                                │
│                  │  ○  Team standup notes               03/16       │
│                  │                                                   │
│                  │                                                   │
│                  │                              [f] hide done        │
├──────────────────┴──────────────────────────────────────────────────┤
│  Subtasks: Update dependencies                              (3)      │  ← only
│  ───────────────────────────────────────────────────────────────    │     when
│  ✓  Bump google-api-python-client                                   │     task
│  ○  Bump textual                                                    │     has
│  ○  Test after upgrade                                              │     children
├─────────────────────────────────────────────────────────────────────┤
│  q Quit  w Sync  o New  r Rename  d Delete  c Toggle  ? Help        │  ← Footer
└─────────────────────────────────────────────────────────────────────┘
```

---

## Panel proportions

- Left (Lists): 25% width, full height minus subtask panel
- Right (Tasks): 75% width, full height minus subtask panel
- Bottom (Subtasks): visible only when selected task has children, max 8 lines tall
- Header: 1 line (Textual built-in)
- Footer: 1 line (Textual built-in, auto-generated from BINDINGS)

---

## Visual style

Colors (defined in Textual CSS):
- Active panel border: `cyan` / `$accent`
- Inactive panel border: `$surface` (dim)
- Selected item: reverse highlight (white on blue)
- Active list name: `yellow bold`
- Completed task: `green dim`
- Subtask panel border: `magenta`
- Due date: `$text-muted`
- Note indicator (📝): shown inline before title

Typography:
- Task status symbols: `○` for pending, `✓` for completed (same as current)
- Subtask indicator: `⤵N` where N is count (same as current)
- Note indicator: `📝` inline

---

## Interaction model

### Navigation
- `Tab` / `Shift+Tab` — move focus between panels (replaces h/l)
- `j` / `k` or arrow keys — move selection within active panel
- `Enter` / `l` — drill into subtasks of selected task
- `Esc` / `h` — go back up from subtasks

### Actions (same keybindings as unicurses version for muscle memory)
- `o` — new task/list
- `r` — rename selected
- `d` — delete selected
- `c` — toggle complete
- `a` — set due date
- `i` — edit notes (opens editor via $EDITOR, same as current)
- `p` — paste from buffer
- `w` — sync to Google
- `q` — quit (syncs if dirty)
- `f` — toggle hide completed
- `m` — move task to another list
- `?` — help overlay

### Input dialogs
Use Textual's built-in `Input` widget inside a modal `Screen` for:
- New task title
- Rename task/list
- Due date entry

This is cleaner than the current bottom-of-screen input bar.

---

## Help overlay

Press `?` to show a centered modal with all keybindings, split by context
(lists panel vs tasks panel), same as the current version but styled with
Textual's `ModalScreen`.

---

## Stretch goals (not for first version)

- Search/filter tasks with `/` key
- Color-coded due dates (overdue = red, today = yellow, future = normal)
- Drag-and-drop list reordering (Textual supports mouse events)
- Task detail side panel instead of bottom panel
