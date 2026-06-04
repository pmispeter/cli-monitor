# Repository Guidelines

## Project Structure & Module Organization

This Python package monitors wrapped Claude/Codex-style CLI sessions.

- `cli_monitor/cli.py` defines the `cli-monitor` command, argument parsing, status rendering, and command dispatch.
- `cli_monitor/wrapper.py` runs monitored commands through a PTY and records input/output activity.
- `cli_monitor/store.py` owns session persistence under `~/.local/state/cli-monitor/sessions/` or `$XDG_STATE_HOME/cli-monitor/sessions/`.
- `cli_monitor/tui.py` contains the Textual watch UI.
- `README.md` documents user-facing install and usage flows.
- `docs/` holds supporting research notes.

There is no `tests/` directory yet. Add one at the repository root when introducing automated tests.

## Build, Test, and Development Commands

- `python3 -m pip install -e .` installs the package in editable mode and exposes `cli-monitor`.
- `cli-monitor run -- codex` runs a monitored command through the wrapper.
- `cli-monitor list` lists active wrapped sessions.
- `cli-monitor list --all` includes completed or gone sessions.
- `cli-monitor watch` opens the live Textual TUI.
- `cli-monitor prune` removes completed or gone session JSON files.

When validating without installing, use module entry points where practical, for example `python3 -m cli_monitor.cli list`.

## Coding Style & Naming Conventions

Use Python 3.10+ syntax and keep type annotations consistent with the codebase (`str | None`, `list[dict[str, str]]`). Follow four-space indentation and prefer small, single-purpose functions.

Use `snake_case` for functions, variables, and module-level helpers. Keep implementation-detail helpers private with a leading underscore, as in `wrapper.py`.

No formatter or linter is configured in `pyproject.toml`; avoid broad style-only rewrites unless adding tooling.

## Testing Guidelines

Automated tests are not configured. For new behavior, add focused `pytest` tests under `tests/` and name files `test_<module>.py`.

Prioritize pure logic tests for status calculation, timestamp parsing, row rendering, and session store behavior. PTY and terminal changes should include a manual validation note because they depend on real terminal behavior.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `Use Textual for watch TUI` and `Add setup.sh`. Keep commit titles concise and action-oriented.

Pull requests should include a brief problem statement, a summary of code changes, test or manual validation results, and any user-facing command/output changes. Link related issues when available. Include screenshots or terminal captures for TUI changes.

## Security & Configuration Tips

Session files may contain command paths and working directories. Do not add captured session JSON, local virtualenvs, or machine-specific state to version control.
