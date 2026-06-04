from __future__ import annotations

import json
import os
import signal
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "cli-monitor"
    return Path.home() / ".local" / "state" / "cli-monitor"


def sessions_dir() -> Path:
    path = state_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Session:
    id: str
    pid: int
    command: list[str]
    cwd: str
    tty: str | None
    started_at: str
    updated_at: str
    last_output_at: str | None = None
    last_input_at: str | None = None
    last_key_at: str | None = None
    last_active_at: str | None = None
    window_id: str | None = None
    window_role: str | None = None
    window_class: str | None = None
    gtk_window_object_path: str | None = None
    gtk_unique_bus_name: str | None = None
    gtk_application_id: str | None = None
    tmux_pane: str | None = None
    tmux_socket: str | None = None
    tmux_session_id: str | None = None
    tmux_session_name: str | None = None
    tmux_window_id: str | None = None
    tmux_window_index: str | None = None
    tmux_pane_id: str | None = None
    tmux_pane_index: str | None = None
    exit_code: int | None = None
    ended_at: str | None = None

    @property
    def path(self) -> Path:
        return sessions_dir() / f"{self.id}.json"


def write_session(session: Session) -> None:
    session.updated_at = utc_now()
    payload = asdict(session)
    target = session.path
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        delete=False,
        prefix=f".{target.name}.",
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=True, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)


def read_sessions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(sessions_dir().glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                rows.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def delete_session(session_id: str) -> None:
    path = sessions_dir() / f"{session_id}.json"
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process_group(pid: int, sig: int = signal.SIGTERM) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass
