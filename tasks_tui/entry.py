"""Console-script entrypoint: decides between the TUI and the CLI.

This module deliberately imports neither `unicurses` nor `tasks_tui.main` at
module scope. `main.py` does `from unicurses import *`, which initializes
terminal state — a CLI query must never pay that cost, and must work when no
terminal is attached at all.

Routing rule: any arguments at all mean the CLI. Bare `tasks-tui` (empty argv)
launches the TUI. This is deliberately dumb — a typo'd verb like `favs` must
land in `cli.run()` and get argparse's "invalid choice" error, not silently
fall through to the TUI, which ignores argv entirely and would leave the user
looking at a full-screen curses app with no idea why their command didn't work.
"""

import sys


def main():
    argv = sys.argv[1:]

    is_cli = bool(argv)
    if is_cli:
        from . import cli

        sys.exit(cli.run(argv))

    from .main import cli as tui

    tui()
