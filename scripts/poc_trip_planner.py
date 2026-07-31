"""Entry point runner for the interactive terminal trip planner CLI.

This script delegates core logic to `src.services`, `src.agents`, and `src.cli`.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.cli.terminal_chat import run_terminal_chat


def main():
    """Run the interactive terminal chat CLI."""
    run_terminal_chat()


if __name__ == "__main__":
    main()
