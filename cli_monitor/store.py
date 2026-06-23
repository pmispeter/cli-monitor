from __future__ import annotations

import json
import os
import signal
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote


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


def suppressed_sessions_dir() -> Path:
    path = state_dir() / "deleted-sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def suppressed_session_path(session_id: str) -> Path:
    return suppressed_sessions_dir() / f"{quote(session_id, safe='')}.json"


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


def read_sessions(include_suppressed: bool = False) -> list[dict[str, Any]]:
    suppressed_ids = set() if include_suppressed else suppressed_session_ids()
    rows: list[dict[str, Any]] = []
    for path in sorted(sessions_dir().glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        session_id = payload.get("id")
        if isinstance(session_id, str) and session_id in suppressed_ids:
            continue
        rows.append(payload)
    return rows


def delete_session(session_id: str) -> None:
    path = sessions_dir() / f"{session_id}.json"
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def suppress_session(session_id: str, pid: int | None = None) -> None:
    target = suppressed_session_path(session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"id": session_id, "deleted_at": utc_now()}
    if pid is not None:
        payload["pid"] = pid
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


def delete_suppressed_session(session_id: str) -> None:
    try:
        suppressed_session_path(session_id).unlink()
    except FileNotFoundError:
        pass


def is_suppressed_session(session_id: str) -> bool:
    return suppressed_session_path(session_id).exists()


def suppressed_session_ids() -> list[str]:
    return [record["id"] for record in suppressed_session_records()]


def suppressed_session_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(suppressed_sessions_dir().glob("*.json")):
        fallback_id = unquote(path.stem)
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            records.append({"id": fallback_id})
            continue
        session_id = payload.get("id")
        if not isinstance(session_id, str) or not session_id:
            session_id = fallback_id
        record = {"id": session_id}
        pid = payload.get("pid")
        if isinstance(pid, int):
            record["pid"] = pid
        records.append(record)
    return records


def prune_orphaned_suppressed_sessions() -> int:
    removed = 0
    for record in suppressed_session_records():
        session_id = record["id"]
        if (sessions_dir() / f"{session_id}.json").exists():
            continue
        pid = record.get("pid")
        if isinstance(pid, int) and pid_alive(pid):
            continue
        delete_suppressed_session(session_id)
        removed += 1
    return removed


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
