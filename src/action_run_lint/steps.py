"""Judge one parsed composite action: is every `run:` step a call of one script?

The one accepted form, for a step whose `shell:` is `bash` or `sh`:

    run: '"$GITHUB_ACTION_PATH/path/to/script"'

`$GITHUB_ACTION_PATH` may also be written `${GITHUB_ACTION_PATH}`. The body is
matched as written, with nothing around the call but the one newline a YAML
block scalar ends with: the double quotes keep a path with a space in it one
word, single quotes would keep the variable from expanding at all, and any
other character the shell reads - a carriage return, a trailing backslash -
could make it run something other than the file checked. The path must name
an executable regular file inside the repository, as the shell will look it up:
`missing/../run.sh` is refused when `missing` does not exist. Nothing else may share the line: no arguments, no second
command, and no `${{ }}` expression anywhere in the body.

Why so narrow: shell written inline in `action.yml` is linted by nothing -
shellcheck reads script files, and actionlint reads an action's metadata, not
its steps - and an expression inside `run:` is pasted into the script text
before the shell parses it, so an input's value becomes code. A step that only
names a file leaves all of its shell where shellcheck reads it, and the
action's inputs reach it as `env:` variables, which the shell quotes.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

SHELLS = ("bash", "sh")
SEGMENT = r"[A-Za-z0-9._-]+"
CALL = re.compile(
    rf""""\$(?:GITHUB_ACTION_PATH|\{{GITHUB_ACTION_PATH\}})/(?P<path>{SEGMENT}(?:/{SEGMENT})*)"\n?"""
)


@dataclass(frozen=True)
class Finding:
    path: str
    step: str
    what: str

    def __str__(self) -> str:
        return f"{self.path}: {self.step}: {self.what}"


def _step_label(index: int, step: Mapping[str, object]) -> str:
    name = step.get("name") or step.get("id")
    return f"step {index + 1} ({name})" if name else f"step {index + 1}"


def _judge_run(root: Path, action_dir: Path, step: Mapping[str, object]) -> list[str]:
    body = step["run"]
    if not isinstance(body, str):
        return ["run is not a string"]
    problems: list[str] = []
    shell = step.get("shell")
    if shell not in SHELLS:
        problems.append(f"shell is {shell!r}; it must be one of {', '.join(SHELLS)}")
    if "${{" in body:
        problems.append("run holds a ${{ }} expression; pass the value through env:")
    match = CALL.fullmatch(body)
    if not match:
        lines = body.rstrip("\n").count("\n") + 1
        if lines > 1:
            problems.append(
                f"run is {lines} lines; it must be one call of a script file"
            )
        else:
            problems.append(
                'run must be exactly "$GITHUB_ACTION_PATH/<script>", double-quoted,'
                " with no arguments"
            )
        return problems
    rel = match.group("path")
    # Looked up as given, so the kernel walks every component as the shell's
    # exec will; containment is judged on the resolved path separately.
    as_written = os.path.join(action_dir, rel)
    if not Path(as_written).resolve().is_relative_to(root.resolve()):
        problems.append(f"{rel} is outside the repository")
    elif not os.path.isfile(as_written):
        problems.append(f"{rel} is not a file")
    elif not os.access(as_written, os.X_OK):
        problems.append(f"{rel} is not executable")
    return problems


# isinstance narrows a parsed YAML value to a container of Unknown, which strict
# pyright rejects; these keep the isinstance test itself and only state what
# the contents are.
def _is_mapping(value: object) -> TypeGuard[Mapping[str, Any]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def judge(root: Path, path: str, action: object) -> list[Finding]:
    if not _is_mapping(action):
        return [Finding(path, "-", "the file is not an action mapping")]
    runs = action.get("runs")
    if not _is_mapping(runs):
        return [Finding(path, "-", "the action has no runs mapping")]
    using = runs.get("using")
    # The runner reads `using` without regard to case.
    if not isinstance(using, str) or using.lower() != "composite":
        return []
    steps = runs.get("steps")
    if not _is_list(steps):
        return [Finding(path, "-", "the composite action has no steps list")]
    action_dir = (root / path).parent
    findings: list[Finding] = []
    for index, step in enumerate(steps):
        if not _is_mapping(step):
            findings.append(Finding(path, f"step {index + 1}", "not a mapping"))
            continue
        if "run" not in step:
            continue
        label = _step_label(index, step)
        findings.extend(
            Finding(path, label, what) for what in _judge_run(root, action_dir, step)
        )
    return findings
