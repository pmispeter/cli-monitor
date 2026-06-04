# cli-monitor

Monitor multiple Claude/Codex-style CLI sessions from one terminal.

`cli-monitor` is a small local-only tool for people who keep several agent CLI
sessions running at once. It wraps interactive CLI commands in a PTY, records
lightweight session metadata, and shows which sessions are new, busy, waiting,
finished, or gone. It does not require network access or call any external
service; the wrapped CLI may still use the network as usual.

[中文 README](README_cn.md)

## Why this exists

When you open more and more Codex or Claude Code terminals across different
projects, it becomes easy to lose track of them. One terminal may have finished
its task and be waiting for your review, another may be stuck waiting for a
confirmation, and another may still be actively producing output. Without a
shared view, you have to switch through every terminal just to answer "which
agent needs me now?"

`cli-monitor` is built for that workflow. Run your agent commands through
`cli-monitor run -- ...`, then use `cli-monitor list` or `cli-monitor watch` to
see the current state of all monitored sessions from one place. The goal is not
to replace Codex or Claude Code; it is to make multi-terminal agent development
easier to supervise.

## Preview

![cli-monitor watch TUI showing live sessions](docs/assets/snapshot.jpg)

## Features

- Wrap any interactive command with `cli-monitor run -- ...`.
- Track Claude and Codex sessions without capturing full terminal transcripts.
- Show live session state, project directory, PID, last visible activity, and
  runtime.
- Quickly see which sessions are waiting for your next action.
- Open a live Textual TUI with keyboard navigation and automatic refresh.
- Focus the selected local terminal window on Linux/X11 when window helpers are
  available.
- Restore recorded tmux window and pane targets when a session was launched
  inside tmux.
- Run fully locally without any network service.
- Store session files locally under XDG state directories.

## Support Status

`cli-monitor` currently targets Linux only and has only been tested on Ubuntu.
Other Unix-like systems may work for basic PTY wrapping, but they are not
supported or verified yet.

Claude Code and OpenAI Codex CLI are the only target CLIs currently documented
and tested. Because `cli-monitor` wraps commands through a PTY, other
interactive CLIs may work too, but they are not treated as supported targets
yet.

For a working local setup, use `setup.sh` to install the package. It also
offers optional desktop helper dependencies used by session focusing.

Reliable window jumping depends on launching monitored sessions inside `tmux`.
Without tmux, `cli-monitor` can still try to focus a matching terminal window
through X11 helpers, but it cannot reliably restore the exact working window or
pane.

## Requirements

- Python 3.10+
- Linux
- `textual` for the watch TUI, installed automatically from `pyproject.toml`

Optional desktop focus helpers prompted by `setup.sh` on Ubuntu/Debian:

- `xdotool`
- `x11-utils` / `xprop`
- `tmux`, required for reliable window/pane jumping

You can skip those optional helpers during setup. `cli-monitor` still installs
and tracks sessions, but automatic terminal focusing and tmux pane restoration
will be limited or unavailable.

The focus feature is local-desktop oriented. It can raise local terminal windows
on supported Linux/X11 desktops, but it cannot focus a terminal on your laptop
from a remote SSH session without an additional local helper.

## Installation

Recommended on Ubuntu/Debian:

```bash
./setup.sh
```

Manual install from a local checkout:

```bash
python3 -m pip install -e .
```

If your system Python blocks user installs, use a virtual environment or `pipx`.

If you install manually and want session focusing, install `xdotool`,
`x11-utils`, and `tmux` yourself.

## Quick Start

Run a monitored Codex session:

```bash
cli-monitor run -- codex
```

Run a monitored Claude session:

```bash
cli-monitor run -- claude
```

Pass arguments to the wrapped CLI after `--`:

```bash
cli-monitor run -- claude --dangerously-skip-permissions
```

In another terminal, list active sessions:

```bash
cli-monitor list
```

Open the live dashboard:

```bash
cli-monitor watch
```

## TUI Controls

Inside `cli-monitor watch`:

| Key | Action |
| --- | --- |
| `q` / `Esc` | Quit |
| `r` | Refresh immediately |
| `a` | Toggle active-only vs all sessions |
| `c` | Clean done/gone sessions after confirmation |
| `Enter` / `Space` | Focus the selected live session |

Double-clicking a session row also tries to focus that session.

## Session States

`cli-monitor` separates visible screen output from submit/control input such as
Enter, Ctrl-C, and Ctrl-D. The default state calculation uses a 5-second output
window:

| State | Meaning |
| --- | --- |
| `new` | The wrapped command has started, but no submit/control input has been recorded yet. |
| `busy` | A submit/control input was recorded and visible output happened recently. |
| `wait` | A submit/control input was recorded, but no visible output has appeared for at least the active window. |
| `done` | The wrapped command exited. |
| `gone` | The recorded process is no longer running. |

Override the active window:

```bash
cli-monitor watch --active-after 10
cli-monitor list --active-after 10
```

Override the TUI refresh interval:

```bash
cli-monitor watch --interval 0.5
```

## Commands

```bash
cli-monitor run -- <command> [args...]
cli-monitor list [--all] [--active-after SECONDS]
cli-monitor watch [--all] [--active-after SECONDS] [--interval SECONDS]
cli-monitor prune
```

`list` and `watch` hide `done` and `gone` sessions by default. Use `--all` to
include them.

`prune` removes session JSON files for `done` and `gone` sessions:

```bash
cli-monitor prune
```

## Shell Aliases

For day-to-day use, wrap your agent CLIs with shell functions:

```bash
codex() {
  cli-monitor run -- /path/to/codex "$@"
}

claude() {
  cli-monitor run -- /path/to/claude "$@"
}
```

Use the absolute path to the real binary if your shell would otherwise resolve
the function recursively.

Do not `cd` inside these functions unless you want every session to show that
directory as its project. `PROJECT` is the basename of the directory where the
wrapped command was started.

## Stored Data

Session files are stored under:

```text
$XDG_STATE_HOME/cli-monitor/sessions/
```

If `XDG_STATE_HOME` is not set, the default is:

```text
~/.local/state/cli-monitor/sessions/
```

Session files contain metadata such as command arguments, working directories,
PIDs, timestamps, terminal/window identifiers, tmux identifiers, and exit codes.
They are not intended to store full command transcripts. `cli-monitor` does not
send this data anywhere.

## Development

Install in editable mode:

```bash
python3 -m pip install -e .
```

Run the test suite:

```bash
python3 -m pytest
```

Run without installing the console script:

```bash
python3 -m cli_monitor.cli list
python3 -m cli_monitor.cli watch
```

## Limitations

- Only sessions started through `cli-monitor run -- ...` are tracked.
- Only Linux is supported right now, and the project has only been tested on
  Ubuntu.
- Window focusing depends on local desktop support, `xdotool`/`xprop`, and tmux
  for reliable target restoration.
- Focus behavior is best on Linux/X11. Wayland support is not verified.
- Remote SSH sessions cannot directly focus your local terminal window.

## License

MIT License. See [LICENSE](LICENSE).
