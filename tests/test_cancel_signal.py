"""Which process a cancelled step's signal reaches, under each accepted form.

GitHub's runner starts a `bash` step as `bash --noprofile --norc -e -o pipefail
<file>` and cancels it by signalling that one process: SIGINT, then SIGTERM
(actions/runner, `src/Runner.Sdk/ProcessInvoker.cs`). These tests start a step
the same way, with a script that reports any signal it catches, and signal the
entry process as the runner does. They are why the `exec` form is accepted: it
is the only one under which the script itself is signalled.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROBE = """#!{python}
import os, signal, sys

def caught(number, frame):
    os.write(1, f"caught {{signal.Signals(number).name}}\\n".encode())
    os._exit(3)

signal.signal(signal.SIGINT, caught)
signal.signal(signal.SIGTERM, caught)
os.write(1, f"ready {{os.getpid()}}\\n".encode())
sys.stdin.readline()
os.write(1, b"caught nothing\\n")
"""


class CancelSignal(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.action_path = Path(directory.name)
        probe = self.action_path / "probe.py"
        probe.write_text(PROBE.format(python=sys.executable))
        probe.chmod(0o755)

    def start(self, run: str) -> tuple[subprocess.Popen[bytes], int]:
        """The step as the runner starts it, once the script is ready for a
        signal, and the script's own process id."""
        step = self.action_path / "step.sh"
        step.write_text(run)
        entry = subprocess.Popen(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(step)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**os.environ, "GITHUB_ACTION_PATH": str(self.action_path)},
        )
        assert entry.stdin is not None and entry.stdout is not None
        # Closing stdin is what releases a script left running by a failed
        # assertion: it reads end of file and exits.
        self.addCleanup(entry.stdout.close)
        self.addCleanup(entry.stdin.close)
        word, pid = entry.stdout.readline().split()
        self.assertEqual(word, b"ready")
        return entry, int(pid)

    def test_under_exec_the_script_is_the_process_signalled(self) -> None:
        entry, script = self.start('exec "$GITHUB_ACTION_PATH/probe.py"\n')
        assert entry.stdout is not None
        self.assertEqual(script, entry.pid)
        entry.send_signal(signal.SIGINT)
        self.assertEqual(entry.stdout.readline(), b"caught SIGINT\n")
        self.assertEqual(entry.wait(), 3)

    def test_under_a_plain_call_the_script_is_never_signalled(self) -> None:
        # bash runs the file's command in a child and waits on it, so the
        # cancel lands on bash: the entry dies and the script runs on, orphaned,
        # having caught nothing. A script that must clean up on cancel cannot.
        entry, script = self.start('"$GITHUB_ACTION_PATH/probe.py"\n')
        assert entry.stdin is not None and entry.stdout is not None
        self.assertNotEqual(script, entry.pid)
        entry.send_signal(signal.SIGINT)
        entry.send_signal(signal.SIGTERM)
        self.assertLess(entry.wait(), 0)
        entry.stdin.write(b"report\n")
        entry.stdin.flush()
        self.assertEqual(entry.stdout.read(), b"caught nothing\n")


if __name__ == "__main__":
    unittest.main()
