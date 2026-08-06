# Tasks TUI

A simple, fast, and intuitive Terminal User Interface (TUI) for Google Tasks.

## Features

*   View your Google Tasks directly in the terminal
*   Add new tasks and lists.
*   Mark tasks as complete.
*   Rename tasks and lists.
*   Switch between your task lists.
*   Add due dates, notes, or subtasks
*   Vim-style keybindings for navigation.

## Screenshots
<img width="1365" height="742" alt="image" src="https://github.com/user-attachments/assets/4c51a8ba-eac3-4a02-ab62-060d91150941" />



## Installation

1.  **Install via pip:**

    ```bash
    pip install tasks-tui-app
    ```

2.  **Clone the repository (optional, for development):**

    ```bash
    git clone https://github.com/your-username/Gtask.git
    cd Gtask
    ```

3.  **Install the dependencies (if cloning for development):**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Enable the Google Tasks API [Guide](https://developers.google.com/workspace/tasks/quickstart/python)**

    *   Go to the [Google API Console](https://console.developers.google.com/).
    *   Create a new project.
    *   Enable the **Google Tasks API** for your project.
    *   Create an **OAuth 2.0 Client ID** for a **Desktop application**.
    *   Download the JSON file and rename it to `client_secrets.json`.
    *   Place the `client_secrets.json` file in the ~/.gtask.

## Usage

To run the application, use the following command:

```bash
tasks-tui
```

### Command line queries

The same command answers quick questions without opening the TUI. These read
the local cache only — no network, no sign-in, roughly 30ms.

```bash
tasks-tui fav              # starred tasks, all lists
tasks-tui lists            # every list with undone/total counts
tasks-tui list Work        # tasks in one list (partial names work)
tasks-tui today            # due today
tasks-tui overdue          # past due, not done
tasks-tui search milk      # match title or notes
tasks-tui sync             # pull fresh data from Google
tasks-tui done N            # mark task N done (number from the last listing) and push to Google
```

Flags: `-a` (include completed), `--json` (machine-readable), `-q` (hide staleness).
On `fav`, `today`, `overdue`, and `search`, add `-l NAME` to restrict to one list.

Without a local cache, exits 1 with the message: `no local cache; run 'tasks-tui sync' or launch the TUI first`.
Exit codes: 0 (success), 1 (runtime error), 2 (usage error).

`fav`, `list`, `today`, `overdue`, and `search` number each task in
their pretty-mode output (not in piped/plain or `--json` output — those
are unchanged). `tasks-tui done N` marks that task done and pushes the
change to Google before it returns. The number is only valid until the
next listing command overwrites it — run a listing command, then `done`
right after, don't reuse an old number.

```
$ tasks-tui fav
Home
1    ○ Buy milk
Work
2    ○ Ship CLI mode        due 2026-08-05

$ tasks-tui done 2
✓ marked "Ship CLI mode" done — synced
```

Running `done` on a task that's already done is a safe no-op — it prints
`"<title>" is already done` and does not touch Google.

Completed tasks are hidden by default, independent of the TUI's
`hide_completed` setting. Output drops colour automatically when piped, and
respects `NO_COLOR`.

Every query prints how old the cache is on stderr, so pipes stay clean:

```
$ tasks-tui fav | grep Ship
synced 3h ago
  ○ Ship CLI mode        due 2026-08-05
```

Run `tasks-tui sync` to refresh. Note that the age is approximate until the
first sync after upgrading.

### Keyboard Shortcuts

| Key          | Action                                  |
| :----------- | :-------------------------------------- |
| `q`          | Quit application                        |
| `w`          | Write and Sync                          |
| `↑` / `k`    | Move selection up                       |
| `↓` / `j`    | Move selection down                     |
| `←` / `h`    | Exit selection                          |
| `→` / `l`    | Enter selection                         |
| `o`          | Open new selection                      |
| `d`          | Delete selection                        |
| `r`          | Rename selection                        |
| `c`          | Toggle task completion                  |
| `a`          | Add due date            |
| `i`          | Insert/view task note   |
| `p`          | Paste from buffer       |
| `?`          | Toggle Help                             |

### Task Status Symbols

| Symbol            | Meaning                                                                                  |
| :-----            | :--------------                                                                          |
| `[ ]`             | Task needs action                                                                        |
| `[X]`             | Task completed                                                                           |
| `('Task Counts')` | Count of tasks/subtasks within (subtasks of subtasks do not display in web Google Tasks) |

When you run the application for the first time, it will open a web browser and ask you to authorize the application to access your Google Tasks. After you authorize the application, it will create a `token.json` file in the `~/.gtask` directory. This file contains your access and refresh tokens, so you won't have to authorize the application every time you run it. (Occasionally your token might become expire, so just delete `token.json` from `~/.gtask` and rerun the application to reauthenticate!)

## Contributing

Contributions are welcome! If you have any ideas, suggestions, or bug reports, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
