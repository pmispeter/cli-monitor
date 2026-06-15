from __future__ import annotations

import os
import pty
import select
import signal
import sys
import termios
import time
import tty
import uuid
from datetime import datetime, timezone

from .focus import capture_launch_context
from .store import Session, terminate_process_group, utc_now, write_session


def _strip_ansi(data: bytes) -> bytes:
    cleaned = bytearray()
    i = 0
    while i < len(data):
        byte = data[i]
        if byte == 0x1B:
            i += 1
            if i >= len(data):
                break
            marker = data[i]
            if marker in b"[":
                i += 1
                while i < len(data):
                    if 0x40 <= data[i] <= 0x7E:
                        i += 1
                        break
                    i += 1
                continue
            if marker in b"]":
                i += 1
                while i < len(data):
                    if data[i] == 0x07:
                        i += 1
                        break
                    if data[i : i + 2] == b"\x1b\\":
                        i += 2
                        break
                    i += 1
                continue
            i += 1
            continue
        if byte < 0x20 and byte not in (0x09, 0x0A, 0x0D):
            i += 1
            continue
        cleaned.append(byte)
        i += 1
    return bytes(cleaned)


def _normalize_echo_input(data: bytes) -> bytes:
    normalized = bytearray()
    i = 0
    while i < len(data):
        byte = data[i]
        if byte == 0x1B:
            i += 1
            if i < len(data) and data[i] in b"[":
                i += 1
                while i < len(data):
                    if 0x40 <= data[i] <= 0x7E:
                        i += 1
                        break
                    i += 1
                continue
            i += 1
            continue
        if byte in (0x0A, 0x0D):
            normalized.append(0x0D)
        elif byte >= 0x20 or byte == 0x09:
            normalized.append(byte)
        i += 1
    return bytes(normalized)


def _strip_focus_events(data: bytes) -> bytes:
    return data.replace(b"\x1b[I", b"").replace(b"\x1b[O", b"")


def _has_focus_event(data: bytes) -> bool:
    return b"\x1b[I" in data or b"\x1b[O" in data


def _tracking_input(data: bytes) -> bytes:
    return _strip_focus_events(data)


def _is_submit_input(data: bytes) -> bool:
    return any(byte in data for byte in (0x03, 0x04, 0x0A, 0x0D))


def _strip_echo(data: bytes, pending_echo: bytearray) -> bytes:
    visible = _strip_ansi(data)
    if not visible or not pending_echo:
        return visible

    pos = 0
    while pos < len(visible) and pending_echo:
        if visible[pos : pos + 2] == b"\r\n" and pending_echo[:1] == b"\r":
            del pending_echo[:1]
            pos += 2
            continue
        if visible[pos : pos + 1] == pending_echo[:1]:
            del pending_echo[:1]
            pos += 1
            continue
        break
    return visible[pos:]


def _copy_winsize(src_fd: int, dst_fd: int) -> None:
    try:
        import fcntl
        import struct

        size = fcntl.ioctl(src_fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xpixels, ypixels = struct.unpack("HHHH", size)
        fcntl.ioctl(dst_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, xpixels, ypixels))
    except OSError:
        pass


def run_wrapped(command: list[str]) -> int:
    if not command:
        print("cli-monitor run: missing command", file=sys.stderr)
        return 2

    session_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    pid, master_fd = pty.fork()

    if pid == 0:
        os.execvp(command[0], command)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    old_termios = termios.tcgetattr(stdin_fd) if sys.stdin.isatty() else None
    child_exited = False
    exit_code = 0

    session = Session(
        id=session_id,
        pid=pid,
        command=command,
        cwd=os.getcwd(),
        tty=os.ttyname(stdin_fd) if sys.stdin.isatty() else None,
        started_at=utc_now(),
        updated_at=utc_now(),
        **capture_launch_context(),
    )
    write_session(session)

    def on_winch(_signum: int, _frame: object) -> None:
        nonlocal suppress_output_until
        suppress_output_until = time.monotonic() + 1.0
        _copy_winsize(stdin_fd, master_fd)

    old_winch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, on_winch)
    _copy_winsize(stdin_fd, master_fd)

    try:
        if old_termios is not None:
            tty.setraw(stdin_fd)

        last_flush = 0.0
        input_open = True
        pending_echo = bytearray()
        suppress_output_until = 0.0
        while True:
            read_fds = [master_fd]
            if input_open:
                read_fds.append(stdin_fd)
            readable, _, _ = select.select(read_fds, [], [], 0.25)

            if master_fd in readable:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""
                if not data:
                    break
                os.write(stdout_fd, data)
                output_visible = _strip_echo(data, pending_echo)
                if output_visible and time.monotonic() >= suppress_output_until:
                    now_iso = utc_now()
                    session.last_output_at = now_iso
                    session.last_active_at = session.last_output_at

            if input_open and stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, 4096)
                except OSError:
                    data = b""
                if data:
                    os.write(master_fd, data)
                    if _has_focus_event(data):
                        suppress_output_until = time.monotonic() + 1.0
                    tracked_input = _tracking_input(data)
                    if tracked_input:
                        pending_echo.extend(_normalize_echo_input(tracked_input))
                        session.last_key_at = utc_now()
                        if _is_submit_input(tracked_input):
                            session.last_input_at = session.last_key_at
                else:
                    input_open = False

            now = time.monotonic()
            if now - last_flush >= 1.0:
                write_session(session)
                last_flush = now

            if not child_exited:
                try:
                    waited_pid, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    child_exited = True
                    input_open = False
                else:
                    if waited_pid == pid:
                        child_exited = True
                        input_open = False
                        if os.WIFEXITED(status):
                            exit_code = os.WEXITSTATUS(status)
                        elif os.WIFSIGNALED(status):
                            exit_code = 128 + os.WTERMSIG(status)
    except KeyboardInterrupt:
        terminate_process_group(pid, signal.SIGINT)
    finally:
        if old_termios is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_termios)
        signal.signal(signal.SIGWINCH, old_winch)

        if not child_exited:
            try:
                _, status = os.waitpid(pid, 0)
                if os.WIFEXITED(status):
                    exit_code = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    exit_code = 128 + os.WTERMSIG(status)
            except ChildProcessError:
                pass

        session.exit_code = exit_code
        session.ended_at = utc_now()
        write_session(session)

    return exit_code
