from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any

from .store import delete_session, pid_alive, read_sessions
from .wrapper import run_wrapped


DEFAULT_WATCH_INTERVAL = 1.0


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def age(value: str | None, now: datetime) -> str:
    seconds = seconds_since(value, now)
    if seconds is None:
        return "-"
    return format_elapsed(seconds)


def elapsed_between(start_value: str | None, end_value: str | None, now: datetime) -> str:
    start = parse_ts(start_value)
    if start is None:
        return "-"
    end = parse_ts(end_value) or now
    return format_elapsed(max(0, int((end - start).total_seconds())))


def seconds_since(value: str | None, now: datetime) -> int | None:
    ts = parse_ts(value)
    if ts is None:
        return None
    return max(0, int((now - ts).total_seconds()))


def format_elapsed(seconds: int) -> str:
    if seconds < 100 * 60 * 60:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining_seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    return f"{days}d {hours:02d}:{minutes:02d}"


def display_status(session: dict[str, Any], now: datetime, active_after: int) -> str:
    if session.get("ended_at") is not None:
        return "done"
    pid = session.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return "gone"
    has_input_tracking = "last_input_at" in session
    if has_input_tracking and parse_ts(session.get("last_input_at")) is None:
        return "new"
    last_active = parse_ts(last_active_at(session))
    if last_active is None:
        if has_input_tracking:
            return "wait"
        return "new"
    seconds_since_output = (now - last_active).total_seconds()
    if seconds_since_output >= active_after:
        return "wait"
    return "busy"


def last_active_at(session: dict[str, Any]) -> str | None:
    # Prefer the explicit output timestamp. `last_active_at` is kept as a
    # fallback for older session files written before output and input were
    # separated.
    return session.get("last_output_at") or session.get("last_active_at")


def project_name(cwd: str) -> str:
    path = os.path.normpath(cwd)
    name = os.path.basename(path)
    return name or path


def command_parts(session: dict[str, Any]) -> list[str]:
    command = session.get("command") or []
    if isinstance(command, list):
        return [str(part) for part in command]
    return str(command).split()


def cli_name(session: dict[str, Any]) -> str:
    for part in command_parts(session)[:3]:
        keyword = os.path.basename(part).lower()
        if "claude" in keyword:
            return "claude"
        if "codex" in keyword:
            return "codex"
    return "-"


def session_key(session: dict[str, Any]) -> str:
    session_id = session.get("id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return "|".join(
        str(session.get(key, ""))
        for key in ("pid", "cwd", "started_at")
    )


def trim(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def session_rows(active_after: int, show_all: bool = False) -> list[dict[str, str]]:
    now = datetime.now(timezone.utc)
    rows: list[dict[str, str]] = []
    for session in read_sessions():
        status = display_status(session, now, active_after)
        if not show_all and status in {"done", "gone"}:
            continue
        last_active = last_active_at(session)
        idle_seconds = seconds_since(last_active, now)
        if idle_seconds is None:
            idle_seconds = seconds_since(session.get("started_at"), now)
        active_label = "working" if status == "busy" else age(last_active, now)
        rows.append(
            {
                "id": session_key(session),
                "cli": cli_name(session),
                "status": status,
                "project": project_name(str(session.get("cwd", "-"))),
                "active": active_label,
                "idle_seconds": "" if idle_seconds is None else str(idle_seconds),
                "pid": str(session.get("pid", "-")),
                "tty": str(session.get("tty") or ""),
                "window_id": str(session.get("window_id") or ""),
                "window_role": str(session.get("window_role") or ""),
                "window_class": str(session.get("window_class") or ""),
                "gtk_window_object_path": str(session.get("gtk_window_object_path") or ""),
                "gtk_unique_bus_name": str(session.get("gtk_unique_bus_name") or ""),
                "gtk_application_id": str(session.get("gtk_application_id") or ""),
                "tmux_pane": str(session.get("tmux_pane") or ""),
                "tmux_socket": str(session.get("tmux_socket") or ""),
                "tmux_session_id": str(session.get("tmux_session_id") or ""),
                "tmux_session_name": str(session.get("tmux_session_name") or ""),
                "tmux_window_id": str(session.get("tmux_window_id") or ""),
                "tmux_window_index": str(session.get("tmux_window_index") or ""),
                "tmux_pane_id": str(session.get("tmux_pane_id") or ""),
                "tmux_pane_index": str(session.get("tmux_pane_index") or ""),
                "runtime": elapsed_between(session.get("started_at"), session.get("ended_at"), now),
            }
        )
    return rows


def render_sessions(rows: list[dict[str, str]], width: int, show_all: bool = False) -> list[str]:
    table_width = max(54, width)
    content_width = table_width - 4
    cli_width = 7
    status_width = 6
    active_width = 11
    pid_width = 7
    runtime_width = 11
    project_width = max(
        6,
        content_width - cli_width - status_width - active_width - pid_width - runtime_width - 5,
    )

    def line(text: str = "") -> str:
        return f"| {trim(text, content_width).ljust(content_width)} |"

    def separator() -> str:
        return f"+{'-' * (table_width - 2)}+"

    def format_row(row: dict[str, str]) -> str:
        cells = (
            f"{trim(row['cli'], cli_width):<{cli_width}}",
            f"{trim(row['status'], status_width):<{status_width}}",
            f"{trim(row['project'], project_width):<{project_width}}",
            f"{trim(row['active'], active_width):>{active_width}}",
            f"{trim(row['pid'], pid_width):>{pid_width}}",
            f"{trim(row['runtime'], runtime_width):>{runtime_width}}",
        )
        return line(" ".join(cells))

    lines = [separator()]
    mode = "all sessions" if show_all else "live sessions"
    lines.append(line(f"cli-monitor - {mode} ({len(rows)})"))
    lines.append(separator())

    if not rows:
        lines.append(line("No wrapped sessions found."))
        lines.append(separator())
        return lines

    header = {
        "cli": "CLI",
        "status": "STATE",
        "project": "PROJECT",
        "active": "LAST_ACTIVE",
        "pid": "PID",
        "runtime": "RUNTIME",
    }
    lines.append(format_row(header))
    lines.append(separator())
    for row in rows:
        lines.append(format_row(row))
    lines.append(separator())
    return lines


def print_sessions(active_after: int, show_all: bool = False) -> None:
    rows = session_rows(active_after, show_all)
    width = shutil.get_terminal_size((100, 20)).columns

    for line in render_sessions(rows, width, show_all):
        print(line)


def watch_sessions(active_after: int, interval: float, show_all: bool = False) -> int:
    if not sys.stdout.isatty():
        try:
            while True:
                print_sessions(active_after, show_all)
                sys.stdout.flush()
                time.sleep(interval)
        except KeyboardInterrupt:
            return 130

    try:
        from .tui import run_tui
    except ImportError as exc:
        print(f"cli-monitor watch: Textual is not installed ({exc})", file=sys.stderr)
        return 1

    try:
        return run_tui(active_after, interval, show_all)
    except KeyboardInterrupt:
        return 130


def prunable_session_ids() -> list[str]:
    now = datetime.now(timezone.utc)
    session_ids: list[str] = []
    for session in read_sessions():
        status = display_status(session, now, active_after=5)
        if status in {"done", "gone"}:
            session_id = session.get("id")
            if isinstance(session_id, str):
                session_ids.append(session_id)
    return session_ids


def prune_done_or_gone_sessions() -> int:
    removed = 0
    for session_id in prunable_session_ids():
        delete_session(session_id)
        removed += 1
    return removed


def prune_sessions() -> int:
    removed = prune_done_or_gone_sessions()
    print(f"Removed {removed} done or gone session(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli-monitor")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    run = subparsers.add_parser("run", help="run a CLI command through the monitor wrapper")
    run.add_argument("command", nargs=argparse.REMAINDER)

    list_cmd = subparsers.add_parser("list", help="list wrapped sessions")
    list_cmd.add_argument("--active-after", type=int, default=5, help="seconds without screen output before wait")
    list_cmd.add_argument("--all", action="store_true", help="include done and gone sessions")

    watch = subparsers.add_parser("watch", help="refresh the session list")
    watch.add_argument("--active-after", type=int, default=5, help="seconds without screen output before wait")
    watch.add_argument("--interval", type=float, default=DEFAULT_WATCH_INTERVAL, help="refresh interval in seconds")
    watch.add_argument("--all", action="store_true", help="include done and gone sessions")

    subparsers.add_parser("prune", help="delete done and gone session records")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command_name == "run":
        command = args.command
        if command and command[0] == "--":
            command = command[1:]
        return run_wrapped(command)
    if args.command_name == "list":
        print_sessions(args.active_after, args.all)
        return 0
    if args.command_name == "watch":
        return watch_sessions(args.active_after, args.interval, args.all)
    if args.command_name == "prune":
        return prune_sessions()

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
