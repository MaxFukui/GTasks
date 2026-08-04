"""Console-script entrypoint: decides between the TUI and the CLI.

This module deliberately imports neither `unicurses` nor `tasks_tui.main` at
module scope. `main.py` does `from unicurses import *`, which initializes
terminal state — a CLI query must never pay that cost, and must work when no
terminal is attached at all.
"""

import sys


def main():
    argv = sys.argv[1:]

    from .cli import VERBS

    is_cli = bool(argv) and (argv[0] in VERBS or argv[0].startswith("-"))
    if is_cli:
        from . import cli

        sys.exit(cli.run(argv))

    from .main import cli as tui

    tui()
