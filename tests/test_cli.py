"""Tests for the `action-run-lint` command: which files it reads, that it
judges the document GitHub sees, and that a lint that could not run never
exits clean. They need git and mikefarah's yq on PATH."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from action_run_lint.cli import main

OK = (
    "runs:\n  using: composite\n  steps:\n"
    "    - name: Ok\n      shell: sh\n"
    "      run: '\"$GITHUB_ACTION_PATH/lib/ok.sh\"'\n"
)
INLINE = (
    "runs:\n  using: composite\n  steps:\n"
    "    - name: Inline\n      shell: bash\n      run: |\n        set -eu\n        echo hi\n"
)


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = main(argv)
    return status, out.getvalue(), err.getvalue()


class TheCommand(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        subprocess.run(["git", "init", "-q"], check=True)

    def action(self, rel: str, text: str, track: bool = True) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if track:
            subprocess.run(["git", "add", rel], check=True)

    def script(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)

    def test_tracked_actions_at_any_depth_are_judged(self) -> None:
        self.script("lib/ok.sh")
        self.action("action.yml", OK)
        self.action("save/action.yaml", INLINE)
        self.action("untracked/action.yml", INLINE, track=False)
        status, out, _ = run([])
        self.assertEqual(status, 1)
        self.assertEqual(
            out,
            "save/action.yaml: step 1 (Inline): run is 2 lines; "
            "it must be one call of a script file\n",
        )

    def test_an_alias_is_judged_as_what_it_names(self) -> None:
        # A text scan would read `*body` as one line; GitHub reads its anchor.
        self.action(
            "action.yml",
            "runs:\n  using: composite\n  steps:\n"
            '    - {shell: sh, run: &body "a\\nb"}\n'
            "    - {shell: sh, run: *body}\n",
        )
        status, out, _ = run([])
        self.assertEqual(status, 1)
        self.assertEqual(out.count("run is 2 lines"), 2)

    def test_from_a_subdirectory_the_whole_repository_is_read(self) -> None:
        # Run from elsewhere in the tree, a listing relative to the current
        # directory would miss the root action, and an empty run would pass.
        self.action("action.yml", INLINE)
        (self.root / "lib").mkdir()
        os.chdir(self.root / "lib")
        status, out, _ = run([])
        self.assertEqual(status, 1)
        self.assertTrue(out.startswith("action.yml: step 1 (Inline):"))

    def test_a_named_file_keeps_the_repository_boundary(self) -> None:
        # Named from a subdirectory, a nested action's `../lib` script is still
        # inside the repository, as it is when the action is found by listing.
        self.script("lib/save.sh")
        self.action(
            "save/action.yml",
            "runs:\n  using: composite\n  steps:\n"
            "    - shell: sh\n      run: '\"$GITHUB_ACTION_PATH/../lib/save.sh\"'\n",
        )
        os.chdir(self.root / "save")
        self.assertEqual(run(["action.yml"]), (0, "", ""))

    def test_a_named_symlinked_action_is_judged_where_it_is_named(self) -> None:
        # GitHub runs a/action.yml from a/, whatever the file links to, so its
        # script is looked for in a/ whether the action is named or listed.
        self.script("b/run.sh")
        (self.root / "b/action.yml").write_text(OK.replace("lib/ok.sh", "run.sh"))
        (self.root / "a").mkdir()
        (self.root / "a/action.yml").symlink_to("../b/action.yml")
        subprocess.run(["git", "add", "a/action.yml", "b/action.yml"], check=True)
        listed, named = run([]), run(["a/action.yml"])
        self.assertEqual(listed[0], 1)
        self.assertEqual(named, listed)
        self.assertIn("a/action.yml: step 1 (Ok): run.sh is not a file", named[1])

    def test_a_clean_repository_exits_zero(self) -> None:
        self.script("lib/ok.sh")
        self.action("action.yml", OK)
        self.assertEqual(run([]), (0, "", ""))

    def test_a_file_yq_cannot_parse_fails_rather_than_passing(self) -> None:
        self.action("action.yml", "runs: [unclosed\n")
        status, out, err = run([])
        self.assertEqual((status, out), (1, ""))
        self.assertIn("parsing action.yml failed", err)

    def test_without_yq_it_fails_rather_than_passing(self) -> None:
        self.action("action.yml", OK)
        only_git = self.root / "bin"
        only_git.mkdir()
        git = subprocess.run(
            ["git", "--exec-path"], capture_output=True, text=True, check=True
        )
        (only_git / "git").symlink_to(Path(git.stdout.strip()) / "git")
        with mock.patch.dict(os.environ, {"PATH": str(only_git)}):
            status, _, err = run([])
        self.assertEqual(status, 1)
        self.assertIn("yq is not on PATH", err)


if __name__ == "__main__":
    unittest.main()
