from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from cli_monitor.tui import SessionsApp


def _session_row(session_id: str, project: str) -> dict[str, str]:
    return {
        "id": session_id,
        "cli": "codex",
        "status": "busy",
        "project": project,
        "active": "00:00:01",
        "idle_seconds": "1",
        "pid": "123",
        "tty": "",
        "window_id": "",
        "window_role": "",
        "window_class": "",
        "gtk_window_object_path": "",
        "gtk_unique_bus_name": "",
        "gtk_application_id": "",
        "tmux_pane": "",
        "tmux_socket": "",
        "tmux_session_id": "",
        "tmux_session_name": "",
        "tmux_window_id": "",
        "tmux_window_index": "",
        "tmux_pane_id": "",
        "tmux_pane_index": "",
        "runtime": "00:00:05",
    }


class SessionsAppMouseFocusTest(IsolatedAsyncioTestCase):
    def test_summary_uses_two_lines_without_timestamp(self) -> None:
        app = SessionsApp(active_after=5, interval=10)
        rows = [
            _session_row("session-1", "one"),
            _session_row("session-2", "two"),
            {**_session_row("session-3", "three"), "status": "wait"},
        ]

        summary = app._summary_text(rows)

        self.assertEqual(summary.plain, "sessions: live 3\nbusy 2 - wait 1")

    async def test_single_click_selects_row_without_focusing(self) -> None:
        rows = [
            _session_row("session-1", "one"),
            _session_row("session-2", "two"),
        ]
        focused_session_ids: list[str] = []

        def focus_session(row: dict[str, str]) -> object:
            focused_session_ids.append(row["id"])
            return type("FocusResult", (), {"focused": True, "message": "ok"})()

        with (
            patch("cli_monitor.tui.session_rows", return_value=rows),
            patch("cli_monitor.tui.focus_session_window", side_effect=focus_session),
        ):
            app = SessionsApp(active_after=5, interval=10)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.click("#sessions", offset=(2, 2))
                await pilot.pause()
                self.assertEqual(focused_session_ids, [])

    async def test_double_click_focuses_row_once(self) -> None:
        rows = [
            _session_row("session-1", "one"),
            _session_row("session-2", "two"),
        ]
        focused_session_ids: list[str] = []

        def focus_session(row: dict[str, str]) -> object:
            focused_session_ids.append(row["id"])
            return type("FocusResult", (), {"focused": True, "message": "ok"})()

        with (
            patch("cli_monitor.tui.session_rows", return_value=rows),
            patch("cli_monitor.tui.focus_session_window", side_effect=focus_session),
        ):
            app = SessionsApp(active_after=5, interval=10)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.double_click("#sessions", offset=(2, 2))
                await pilot.pause()

        self.assertEqual(focused_session_ids, ["session-2"])
