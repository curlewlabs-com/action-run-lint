"""Tests for judging one parsed composite action's run steps."""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from action_run_lint.steps import judge


class Steps(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def script(self, rel: str, executable: bool = True) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755 if executable else 0o644)

    def whats(self, step: Mapping[str, object], path: str = "action.yml") -> list[str]:
        action = {"runs": {"using": "composite", "steps": [step]}}
        return [f.what for f in judge(self.root, path, action)]

    def test_the_one_form_passes_in_each_spelling(self) -> None:
        self.script("lib/run.sh")
        for run in (
            '"$GITHUB_ACTION_PATH/lib/run.sh"',
            '"${GITHUB_ACTION_PATH}/lib/run.sh"',
            '"$GITHUB_ACTION_PATH/lib/run.sh"\n',
        ):
            with self.subTest(run=run):
                self.assertEqual(self.whats({"shell": "bash", "run": run}), [])

    def test_the_exec_form_passes_in_each_spelling(self) -> None:
        # With exec the script replaces the shell the runner signals on cancel,
        # so it is the process that receives the signal (test_cancel_signal).
        self.script("lib/run.sh")
        for run in (
            'exec "$GITHUB_ACTION_PATH/lib/run.sh"',
            'exec "${GITHUB_ACTION_PATH}/lib/run.sh"',
            'exec "$GITHUB_ACTION_PATH/lib/run.sh"\n',
        ):
            with self.subTest(run=run):
                self.assertEqual(self.whats({"shell": "bash", "run": run}), [])

    def test_exec_takes_nothing_the_plain_call_does_not(self) -> None:
        # Each is the exec form's near miss, and each is shell outside the file
        # again: a second command, arguments or options, a path not under the
        # action, a quoting the shell reads differently, another word in front.
        self.script("lib/run.sh")
        for run in (
            'exec "$GITHUB_ACTION_PATH/lib/run.sh"; echo done',
            'exec "$GITHUB_ACTION_PATH/lib/run.sh" && echo done',
            'exec "$GITHUB_ACTION_PATH/lib/run.sh" "$X"',
            'exec -a lint "$GITHUB_ACTION_PATH/lib/run.sh"',
            'exec "$HOME/lib/run.sh"',
            "exec /bin/sh",
            "exec $GITHUB_ACTION_PATH/lib/run.sh",
            "exec '$GITHUB_ACTION_PATH/lib/run.sh'",
            'exec  "$GITHUB_ACTION_PATH/lib/run.sh"',
            'exec\t"$GITHUB_ACTION_PATH/lib/run.sh"',
            'exec"$GITHUB_ACTION_PATH/lib/run.sh"',
            ' exec "$GITHUB_ACTION_PATH/lib/run.sh"',
            'exec "$GITHUB_ACTION_PATH/lib/run.sh"\r',
            'EXEC "$GITHUB_ACTION_PATH/lib/run.sh"',
            'command "$GITHUB_ACTION_PATH/lib/run.sh"',
            'eval "$GITHUB_ACTION_PATH/lib/run.sh"',
            '. "$GITHUB_ACTION_PATH/lib/run.sh"',
            'builtin exec "$GITHUB_ACTION_PATH/lib/run.sh"',
            'exec exec "$GITHUB_ACTION_PATH/lib/run.sh"',
        ):
            with self.subTest(run=run):
                self.assertEqual(len(self.whats({"shell": "sh", "run": run})), 1)
        self.assertEqual(
            self.whats(
                {"shell": "sh", "run": 'exec "$GITHUB_ACTION_PATH/lib/run.sh"\necho'}
            ),
            ["run is 2 lines; it must be one call of a script file"],
        )

    def test_exec_is_held_to_the_same_script_checks(self) -> None:
        self.script("lib/plain.sh", executable=False)
        for rel, what in (
            ("../../etc/passwd", "../../etc/passwd is outside the repository"),
            ("lib/missing.sh", "lib/missing.sh is not a file"),
            ("lib/plain.sh", "lib/plain.sh is not executable"),
        ):
            with self.subTest(rel=rel):
                run = f'exec "$GITHUB_ACTION_PATH/{rel}"'
                self.assertEqual(self.whats({"shell": "sh", "run": run}), [what])
        self.assertIn(
            "run holds a ${{ }} expression; pass the value through env:",
            self.whats(
                {
                    "shell": "bash",
                    "run": 'exec "$GITHUB_ACTION_PATH/lib/${{ inputs.which }}.sh"',
                }
            ),
        )
        self.assertEqual(
            self.whats({"shell": "python", "run": 'exec "$GITHUB_ACTION_PATH/x"'}),
            ["shell is 'python'; it must be one of bash, sh", "x is not a file"],
        )

    def test_single_quotes_are_refused(self) -> None:
        # Inside single quotes the shell does not expand the variable, so the
        # step would run no file at all, whatever the lint checked.
        self.script("lib/run.sh")
        self.assertEqual(
            len(self.whats({"shell": "sh", "run": "'$GITHUB_ACTION_PATH/lib/run.sh'"})),
            1,
        )

    def test_anything_the_shell_reads_beside_the_call_is_refused(self) -> None:
        # Unquoted, a space in the action's path splits the word; a carriage
        # return or a trailing backslash becomes part of what the shell runs.
        self.script("lib/run.sh")
        for run in (
            "$GITHUB_ACTION_PATH/lib/run.sh",
            '"$GITHUB_ACTION_PATH/lib/run.sh"\r',
            '"$GITHUB_ACTION_PATH/lib/run.sh"\\',
            ' "$GITHUB_ACTION_PATH/lib/run.sh"',
        ):
            with self.subTest(run=run):
                self.assertEqual(len(self.whats({"shell": "sh", "run": run})), 1)

    def test_a_path_is_looked_up_as_the_shell_will(self) -> None:
        # Normalizing first would pass both, and neither runs: `missing` does
        # not exist, and a trailing slash names a directory.
        self.script("lib/run.sh")
        self.assertEqual(
            self.whats(
                {"shell": "sh", "run": '"$GITHUB_ACTION_PATH/missing/../lib/run.sh"'}
            ),
            ["missing/../lib/run.sh is not a file"],
        )
        self.assertEqual(
            len(
                self.whats({"shell": "sh", "run": '"$GITHUB_ACTION_PATH/lib/run.sh/"'})
            ),
            1,
        )

    def test_composite_is_recognized_in_any_case(self) -> None:
        # The runner reads `using` without regard to case, so a mixed-case
        # composite action runs its steps and must be judged.
        action = {
            "runs": {"using": "Composite", "steps": [{"shell": "sh", "run": "a\nb"}]}
        }
        self.assertEqual(len(judge(self.root, "action.yml", action)), 1)

    def test_inline_shell_is_refused(self) -> None:
        # The case the lint exists for: shellcheck never reads these lines.
        self.assertEqual(
            self.whats({"shell": "bash", "run": "set -eu\necho $UNQUOTED\n"}),
            ["run is 2 lines; it must be one call of a script file"],
        )

    def test_a_one_line_command_that_is_not_a_script_call_is_refused(self) -> None:
        self.assertEqual(
            self.whats({"shell": "sh", "run": 'echo "x=1" >> "$GITHUB_OUTPUT"'}),
            [
                (
                    'run must be exactly "$GITHUB_ACTION_PATH/<script>" or'
                    ' exec "$GITHUB_ACTION_PATH/<script>", double-quoted, with no'
                    " arguments"
                )
            ],
        )

    def test_arguments_are_refused(self) -> None:
        # Arguments are shell again, outside the file shellcheck reads.
        self.script("lib/run.sh")
        self.assertEqual(
            len(
                self.whats(
                    {"shell": "sh", "run": '"$GITHUB_ACTION_PATH/lib/run.sh" "$X"'}
                )
            ),
            1,
        )

    def test_an_expression_is_refused_wherever_it_is(self) -> None:
        # An expression is pasted into the script text before the shell parses
        # it, so an input's value becomes code.
        self.script("lib/run.sh")
        whats = self.whats(
            {"shell": "bash", "run": '"$GITHUB_ACTION_PATH/lib/${{ inputs.which }}.sh"'}
        )
        self.assertIn(
            "run holds a ${{ }} expression; pass the value through env:", whats
        )

    def test_another_shell_is_refused(self) -> None:
        self.script("lib/run.py")
        self.assertEqual(
            self.whats({"shell": "python", "run": '"$GITHUB_ACTION_PATH/lib/run.py"'}),
            ["shell is 'python'; it must be one of bash, sh"],
        )

    def test_the_script_must_exist_and_be_executable(self) -> None:
        self.script("lib/plain.sh", executable=False)
        self.assertEqual(
            self.whats({"shell": "sh", "run": '"$GITHUB_ACTION_PATH/lib/missing.sh"'}),
            ["lib/missing.sh is not a file"],
        )
        self.assertEqual(
            self.whats({"shell": "sh", "run": '"$GITHUB_ACTION_PATH/lib/plain.sh"'}),
            ["lib/plain.sh is not executable"],
        )

    def test_a_nested_action_resolves_from_its_own_directory(self) -> None:
        self.script("lib/save.sh")
        (self.root / "save").mkdir()
        step = {"shell": "sh", "run": '"$GITHUB_ACTION_PATH/../lib/save.sh"'}
        self.assertEqual(self.whats(step, path="save/action.yml"), [])

    def test_a_script_outside_the_repository_is_refused(self) -> None:
        step = {"shell": "sh", "run": '"$GITHUB_ACTION_PATH/../../etc/passwd"'}
        self.assertEqual(
            self.whats(step), ["../../etc/passwd is outside the repository"]
        )

    def test_uses_steps_and_other_action_kinds_pass(self) -> None:
        self.assertEqual(self.whats({"uses": "actions/checkout@abc"}), [])
        node = {"runs": {"using": "node24", "main": "index.js"}}
        self.assertEqual(judge(self.root, "action.yml", node), [])

    def test_a_file_that_is_not_an_action_is_refused(self) -> None:
        self.assertEqual(len(judge(self.root, "action.yml", [1])), 1)
        self.assertEqual(len(judge(self.root, "action.yml", {"name": "x"})), 1)

    def test_the_finding_names_file_and_step(self) -> None:
        action = {
            "runs": {
                "using": "composite",
                "steps": [{"uses": "x"}, {"name": "Go", "shell": "sh", "run": "a\nb"}],
            }
        }
        (finding,) = judge(self.root, "action.yml", action)
        self.assertEqual(
            str(finding),
            "action.yml: step 2 (Go): run is 2 lines; it must be one call of a script file",
        )


if __name__ == "__main__":
    unittest.main()
