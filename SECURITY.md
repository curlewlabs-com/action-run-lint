# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
privately via
[GitHub's security advisory feature](https://github.com/curlewlabs-com/action-run-lint/security/advisories/new).

Do not open a public issue for security vulnerabilities.

## Scope

The lint reads action files and runs `git ls-files` and `yq`. It never runs what
it reads. The security surface is:

- **The `git` and `yq` it runs.** These are the first on `PATH`, trusted the way
  `python3` is. Each is given a file name, never file contents as arguments.
- **The files it reads.** These are the repository's tracked action files, or
  the paths named on the command line. It checks that a script a step names
  exists and is executable; it does not read or run the script.
- **A false clean.** A step the lint passes that still holds inline shell or an
  expression in its `run:` is a defect in what the lint promises. Report it as a
  bug, or privately if you think it matters more than that.
