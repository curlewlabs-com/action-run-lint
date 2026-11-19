# action-run-lint

## What it is

A lint for composite GitHub Actions. It fails on any `run:` step in an
`action.yml` that is not one call of a script file:

```text
action.yml: step 1 (Resolve slot): run is 15 lines; it must be one call of a script file
```

The form it accepts, for a step whose `shell:` is `bash` or `sh`:

```yaml
- name: Resolve slot
  shell: bash
  env:
    WINDOW: ${{ inputs.window }}
  run: '"$GITHUB_ACTION_PATH/lib/resolve-slot.sh"'
```

and the same call with `exec` in front, for a script that must see the step
being cancelled:

```yaml
run: 'exec "$GITHUB_ACTION_PATH/lib/build.sh"'
```

## Why it exists

The shell inside a composite action's `run:` steps is the code every consumer's
workflow runs, and no common linter reads it:

- **shellcheck** reads script files, not YAML.
- **actionlint** checks the `run:` blocks of workflows, but reads an
  `action.yml` only as the metadata of an action a workflow calls: it checks the
  inputs a call passes, not the action's own steps. An unquoted variable or a
  reference to an input the action never declares, inside a composite step, is
  reported by neither.

And a `${{ }}` expression in `run:` is substituted into the script text before
the shell parses it, so an input's value becomes shell code: the template
injection GitHub's security guidance warns about. Passing it through `env:`
makes it a variable the shell quotes.

Moving each step's shell into a file fixes both: shellcheck reads all of it, and
the step is left with nothing to inject into. This lint keeps it that way, so
the next step added cannot grow back inline.

## How to use it

As a GitHub Action, after a checkout. Pin it by commit:

```yaml
- uses: actions/checkout@<sha> # vX.Y.Z
  with:
    persist-credentials: false
- uses: curlewlabs-com/action-run-lint@<sha> # vX.Y.Z
```

Then shellcheck the scripts as you would any others.

As a command, from inside a repository, with `git` and
[mikefarah's yq](https://github.com/mikefarah/yq) on `PATH` (GitHub's Linux and
macOS runner images ship both):

```sh
pip install git+https://github.com/curlewlabs-com/action-run-lint@v0.1.2
action-run-lint                  # every tracked action.yml and action.yaml
action-run-lint save/action.yml  # just this one
```

It prints one line per finding and exits 1 on any. It also exits 1, with the
reason on stderr, when it could not run (no `git` or `yq`, a file `yq` cannot
parse), so a lint that did not run never reads as clean.

The action imports from its own package alone, whatever `PYTHONPATH` the job
sets. The command, like any Python program, imports through the `PYTHONPATH` it
inherits, ahead of the standard library: leave out any entry naming the
repository being judged, or a file there named like a module the lint imports
runs in its place.

## Which form to use

When a run is cancelled, the runner signals one process: the shell it started
for the step. It runs a `bash` step as
`bash --noprofile --norc -e -o pipefail <file>` and sends that process SIGINT,
then SIGTERM about 7.5 seconds later; see `src/Runner.Sdk/ProcessInvoker.cs` in
[actions/runner](https://github.com/actions/runner). Bash runs the command in
the file as a child and waits for it, so with the plain call the signal reaches
bash, not your script. Observed with bash 3.2 and 5.3: bash holds the SIGINT
until its child exits, dies on the SIGTERM, and the script keeps running,
orphaned, having been sent nothing. With `exec`, the script replaces bash and
is the process the runner signals.

- Use `exec "$GITHUB_ACTION_PATH/<script>"` when the step's program has to see
  the cancel: to stop a child process cleanly, flush a record, or release
  something it holds. A program the script itself `exec`s becomes, in turn,
  the process signalled.
- Otherwise either form works: a script with nothing to do on a cancel is
  not changed by which process receives it.

`tests/test_cancel_signal.py` starts a step the way the runner does and signals
it, for each form.

## What it checks

For each step with `run:` in an action whose `runs.using` is `composite`, in any
case:

- `shell:` is `bash` or `sh`.
- The body is exactly `"$GITHUB_ACTION_PATH/<path>"` or
  `exec "$GITHUB_ACTION_PATH/<path>"`, with one space after `exec`,
  double-quoted, with nothing around it but the newline a YAML block scalar ends
  with. `${GITHUB_ACTION_PATH}` is accepted. Unquoted, a space in the action's
  path would split the word; single-quoted, the variable would not expand; and
  any other character - an argument, a carriage return, a trailing backslash,
  another word in front - is shell outside the file again.
- No `${{ }}` anywhere in the body.
- `<path>`, looked up from the action file's own directory as the shell will
  look it up, is an executable regular file inside the repository.
  `../lib/save.sh` from `save/action.yml` is fine; `missing/../lib/save.sh` is
  not.

Steps with `uses:`, and actions that are not composite, pass. Each file is
parsed by `yq` with anchors and aliases expanded, so a step is judged as GitHub
reads it.

## License

Licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT license ([LICENSE-MIT](LICENSE-MIT))

at your option. Releases published under the MIT license alone may also be used
under either license.

### Contribution

By submitting a contribution for inclusion in this project, you agree that it
is dual licensed as above, without any additional terms or conditions.
