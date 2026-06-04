from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class FocusResult:
    focused: bool
    message: str


def capture_launch_context() -> dict[str, str | None]:
    context: dict[str, str | None] = {
        "window_id": None,
        "window_role": None,
        "window_class": None,
        "gtk_window_object_path": None,
        "gtk_unique_bus_name": None,
        "gtk_application_id": None,
        "tmux_pane": None,
        "tmux_socket": None,
        "tmux_session_id": None,
        "tmux_session_name": None,
        "tmux_window_id": None,
        "tmux_window_index": None,
        "tmux_pane_id": None,
        "tmux_pane_index": None,
    }
    context.update(_tmux_launch_context())

    window_id = os.environ.get("WINDOWID")
    if window_id:
        try:
            context["window_id"] = hex(int(window_id))
        except ValueError:
            context["window_id"] = window_id
    else:
        context["window_id"] = _active_x11_window_id()

    if context["window_id"]:
        properties = _xprop_properties(str(context["window_id"]))
        context["window_role"] = properties.get("WM_WINDOW_ROLE")
        context["window_class"] = properties.get("WM_CLASS")
        context["gtk_window_object_path"] = properties.get("_GTK_WINDOW_OBJECT_PATH")
        context["gtk_unique_bus_name"] = properties.get("_GTK_UNIQUE_BUS_NAME")
        context["gtk_application_id"] = properties.get("_GTK_APPLICATION_ID")

    return context


def focus_session_window(session: Mapping[str, str]) -> FocusResult:
    status = session.get("status", "")
    if status in {"done", "gone"}:
        return FocusResult(False, f"Cannot focus a {status} session.")

    pid = _parse_pid(session.get("pid", ""))
    if pid is None:
        return FocusResult(False, "Session has no usable PID.")

    candidates = _candidate_pids(pid, session.get("tty", ""))
    if not candidates:
        return FocusResult(False, "No related terminal process found.")

    if _is_tmux_context(session):
        result = _focus_recorded_window(session)
        if not result.focused and shutil.which("xdotool"):
            result = _focus_with_xdotool(candidates)
        if result.focused:
            if _activate_tmux_target(session):
                return FocusResult(True, "Focused terminal window and tmux target.")
            return FocusResult(True, "Focused terminal window; tmux target restore was unavailable.")
        result = _open_tmux_attach_terminal(session)
        if result.focused:
            return result
        if not shutil.which("xdotool"):
            return FocusResult(
                False,
                f"Install xdotool to focus terminal windows. {result.message}",
            )
        return FocusResult(False, f"No matching terminal window found. {result.message}")

    result = _focus_recorded_window(session)
    if result.focused:
        return result

    if shutil.which("xdotool"):
        result = _focus_with_xdotool(candidates)
        if result.focused:
            return result

    if not shutil.which("xdotool"):
        return FocusResult(False, "Install xdotool to focus terminal windows.")

    return FocusResult(False, "No matching terminal window found.")


def _focus_recorded_window(session: Mapping[str, str]) -> FocusResult:
    window_id = session.get("window_id", "")
    if window_id:
        result = _focus_window_id(window_id)
        if result.focused:
            return result

    window_role = session.get("window_role", "")
    if window_role and shutil.which("xdotool"):
        return _focus_with_xdotool_role(window_role)

    return FocusResult(False, "No recorded window found.")


def _is_tmux_context(context: Mapping[str, str | None]) -> bool:
    return bool(context.get("tmux_pane") or context.get("tmux_pane_id") or context.get("tmux_window_id"))


def _focus_window_id(window_id: str) -> FocusResult:
    if shutil.which("xdotool"):
        try:
            focused = subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            focused = None
        if focused is not None and focused.returncode == 0:
            return FocusResult(True, "Focused recorded window.")

    return FocusResult(False, "Recorded window could not be focused.")


def _parse_pid(value: str) -> int | None:
    try:
        pid = int(value)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _candidate_pids(pid: int, tty: str, proc_root: Path = Path("/proc")) -> list[int]:
    candidates: list[int] = []
    _extend_unique(candidates, [pid])
    _extend_unique(candidates, _ancestor_pids(pid, proc_root))

    for tty_pid in _tty_user_pids(tty, proc_root):
        _extend_unique(candidates, [tty_pid])
        _extend_unique(candidates, _ancestor_pids(tty_pid, proc_root))

    return candidates


def _ancestor_pids(pid: int, proc_root: Path = Path("/proc")) -> list[int]:
    ancestors: list[int] = []
    seen = {pid}
    current = pid
    while True:
        parent = _parent_pid(current, proc_root)
        if parent is None or parent <= 1 or parent in seen:
            return ancestors
        ancestors.append(parent)
        seen.add(parent)
        current = parent


def _parent_pid(pid: int, proc_root: Path = Path("/proc")) -> int | None:
    try:
        stat = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None

    _, separator, rest = stat.rpartition(") ")
    if not separator:
        return None
    fields = rest.split()
    if len(fields) < 2:
        return None
    try:
        return int(fields[1])
    except ValueError:
        return None


def _tty_user_pids(tty: str, proc_root: Path = Path("/proc")) -> list[int]:
    if not tty:
        return []

    target = Path(tty)
    try:
        target_resolved = target.resolve(strict=False)
    except OSError:
        target_resolved = target

    pids: list[int] = []
    try:
        proc_entries = list(proc_root.iterdir())
    except OSError:
        return []

    for proc_entry in proc_entries:
        if not proc_entry.name.isdigit():
            continue
        fd_dir = proc_entry / "fd"
        try:
            fd_entries = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd_entry in fd_entries:
            try:
                fd_target = fd_entry.resolve(strict=False)
            except OSError:
                continue
            if fd_target == target_resolved:
                pids.append(int(proc_entry.name))
                break
    return pids


def _extend_unique(target: list[int], values: list[int]) -> None:
    seen = set(target)
    for value in values:
        if value not in seen:
            target.append(value)
            seen.add(value)


def _focus_with_xdotool_role(window_role: str) -> FocusResult:
    try:
        searched = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--role", window_role],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return FocusResult(False, "xdotool could not search windows by role.")
    if searched.returncode != 0:
        return FocusResult(False, "xdotool found no matching window role.")

    for window_id in [line.strip() for line in searched.stdout.splitlines() if line.strip()]:
        try:
            focused = subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if focused.returncode == 0:
            return FocusResult(True, "Focused recorded window.")
    return FocusResult(False, "xdotool found no matching window role.")


def _focus_with_xdotool(candidates: list[int]) -> FocusResult:
    for pid in candidates:
        try:
            searched = subprocess.run(
                ["xdotool", "search", "--pid", str(pid)],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return FocusResult(False, "xdotool could not search windows.")
        if searched.returncode != 0:
            continue

        window_ids = [line.strip() for line in searched.stdout.splitlines() if line.strip()]
        for window_id in window_ids:
            try:
                focused = subprocess.run(
                    ["xdotool", "windowactivate", "--sync", window_id],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if focused.returncode == 0:
                return FocusResult(True, "Focused terminal window.")
    return FocusResult(False, "xdotool found no matching window.")


def _tmux_launch_context() -> dict[str, str | None]:
    context: dict[str, str | None] = {
        "tmux_pane": os.environ.get("TMUX_PANE"),
        "tmux_socket": _tmux_socket(os.environ.get("TMUX")),
        "tmux_session_id": None,
        "tmux_session_name": None,
        "tmux_window_id": None,
        "tmux_window_index": None,
        "tmux_pane_id": None,
        "tmux_pane_index": None,
    }
    pane = context["tmux_pane"]
    if not pane or not shutil.which("tmux"):
        return context

    format_string = "\t".join(
        [
            "#{session_id}",
            "#{session_name}",
            "#{window_id}",
            "#{window_index}",
            "#{pane_id}",
            "#{pane_index}",
        ]
    )
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, format_string],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return context
    if result.returncode != 0:
        return context

    parts = result.stdout.rstrip("\n").split("\t")
    if len(parts) != 6:
        return context

    (
        context["tmux_session_id"],
        context["tmux_session_name"],
        context["tmux_window_id"],
        context["tmux_window_index"],
        context["tmux_pane_id"],
        context["tmux_pane_index"],
    ) = [part or None for part in parts]
    return context


def _activate_tmux_target(session: Mapping[str, str]) -> bool:
    if not shutil.which("tmux"):
        return False

    changed = False
    socket = session.get("tmux_socket", "")
    window_id = session.get("tmux_window_id", "")
    pane_id = session.get("tmux_pane_id", "") or session.get("tmux_pane", "")

    if window_id and _run_tmux(["select-window", "-t", window_id], socket):
        changed = True
    if pane_id and _run_tmux(["select-pane", "-t", pane_id], socket):
        changed = True

    return changed


def _open_tmux_attach_terminal(session: Mapping[str, str]) -> FocusResult:
    if not shutil.which("tmux"):
        return FocusResult(False, "Install tmux to attach tmux sessions.")

    session_target = session.get("tmux_session_id", "") or session.get("tmux_session_name", "")
    if not session_target:
        return FocusResult(False, "No tmux session target recorded.")

    script = _tmux_attach_script(session, session_target)
    for command in _terminal_attach_commands(script):
        try:
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            continue
        return FocusResult(True, "Opened a new terminal attached to tmux target.")

    return FocusResult(False, "No supported terminal emulator found for tmux attach.")


def _tmux_attach_script(session: Mapping[str, str], session_target: str) -> str:
    socket = session.get("tmux_socket", "")
    window_id = session.get("tmux_window_id", "")
    pane_id = session.get("tmux_pane_id", "") or session.get("tmux_pane", "")
    commands: list[str] = []

    if window_id:
        commands.append(_tmux_command_string(["select-window", "-t", window_id], socket))
    if pane_id:
        commands.append(_tmux_command_string(["select-pane", "-t", pane_id], socket))
    commands.append(
        "exec "
        + _tmux_command_string(["attach-session", "-t", session_target], socket)
    )

    return "; ".join(commands)


def _tmux_command_string(arguments: list[str], socket: str = "") -> str:
    command = ["tmux", *arguments]
    if socket:
        command = ["tmux", "-S", socket, *arguments]
    return " ".join(shlex.quote(part) for part in command)


def _terminal_attach_commands(script: str) -> list[list[str]]:
    commands: list[list[str]] = []
    terminal_specs = [
        ("gnome-terminal", ["gnome-terminal", "--", "sh", "-lc", script]),
        ("kgx", ["kgx", "--", "sh", "-lc", script]),
        ("konsole", ["konsole", "-e", "sh", "-lc", script]),
        ("xfce4-terminal", ["xfce4-terminal", "-e", f"sh -lc {shlex.quote(script)}"]),
        ("mate-terminal", ["mate-terminal", "-e", f"sh -lc {shlex.quote(script)}"]),
        ("kitty", ["kitty", "sh", "-lc", script]),
        ("alacritty", ["alacritty", "-e", "sh", "-lc", script]),
        ("wezterm", ["wezterm", "start", "--", "sh", "-lc", script]),
        ("xterm", ["xterm", "-e", "sh", "-lc", script]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "sh", "-lc", script]),
    ]

    for executable, command in terminal_specs:
        if shutil.which(executable):
            commands.append(command)

    return commands


def _run_tmux(arguments: list[str], socket: str = "") -> bool:
    command = ["tmux", *arguments]
    if socket:
        command = ["tmux", "-S", socket, *arguments]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _tmux_socket(value: str | None) -> str | None:
    if not value:
        return None
    socket, separator, _rest = value.partition(",")
    if not separator or not socket:
        return None
    return socket


def _active_x11_window_id() -> str | None:
    if not shutil.which("xprop"):
        return None
    try:
        result = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"#\s*(0x[0-9a-fA-F]+)", result.stdout)
    return match.group(1) if match else None


def _xprop_properties(window_id: str) -> dict[str, str]:
    if not shutil.which("xprop"):
        return {}
    try:
        result = subprocess.run(
            [
                "xprop",
                "-id",
                window_id,
                "WM_CLASS",
                "WM_WINDOW_ROLE",
                "_GTK_WINDOW_OBJECT_PATH",
                "_GTK_UNIQUE_BUS_NAME",
                "_GTK_APPLICATION_ID",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}

    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, separator, raw_value = line.partition("=")
        if not separator:
            continue
        name = name.strip().split("(", 1)[0]
        value = _parse_xprop_value(raw_value.strip())
        if value is not None:
            properties[name] = value
    return properties


def _parse_xprop_value(raw_value: str) -> str | None:
    if raw_value == "not found.":
        return None
    matches = re.findall(r'"([^"]*)"', raw_value)
    if matches:
        return matches[-1]
    return raw_value or None
