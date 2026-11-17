"""`python3 -m action_run_lint`, the command-line entry point; cli.py owns it."""

from action_run_lint.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
