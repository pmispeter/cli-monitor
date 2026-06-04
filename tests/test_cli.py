from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from cli_monitor.cli import (
    DEFAULT_WATCH_INTERVAL,
    build_parser,
    display_status,
    elapsed_between,
    prune_done_or_gone_sessions,
    render_sessions,
    session_rows,
)


class DisplayStatusTest(TestCase):
    def test_alive_session_with_startup_output_before_submit_stays_new(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
        session = {
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": (now - timedelta(seconds=30)).isoformat(),
            "last_input_at": None,
            "last_active_at": None,
            "ended_at": None,
        }

        with patch("cli_monitor.cli.pid_alive", return_value=True):
            self.assertEqual(display_status(session, now, active_after=5), "new")

    def test_alive_session_without_output_stays_new_after_active_after(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
        session = {
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": None,
            "last_active_at": None,
            "ended_at": None,
        }

        with patch("cli_monitor.cli.pid_alive", return_value=True):
            self.assertEqual(display_status(session, now, active_after=5), "new")

    def test_alive_session_with_old_output_is_wait(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
        session = {
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": (now - timedelta(seconds=30)).isoformat(),
            "last_active_at": None,
            "ended_at": None,
        }

        with patch("cli_monitor.cli.pid_alive", return_value=True):
            self.assertEqual(display_status(session, now, active_after=5), "wait")

    def test_alive_session_with_submit_and_no_output_is_wait(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
        session = {
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": None,
            "last_input_at": (now - timedelta(seconds=10)).isoformat(),
            "last_active_at": None,
            "ended_at": None,
        }

        with patch("cli_monitor.cli.pid_alive", return_value=True):
            self.assertEqual(display_status(session, now, active_after=5), "wait")

    def test_alive_session_with_recent_output_after_submit_is_busy(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
        session = {
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": (now - timedelta(seconds=2)).isoformat(),
            "last_input_at": (now - timedelta(seconds=10)).isoformat(),
            "last_active_at": None,
            "ended_at": None,
        }

        with patch("cli_monitor.cli.pid_alive", return_value=True):
            self.assertEqual(display_status(session, now, active_after=5), "busy")


class BuildParserTest(TestCase):
    def test_watch_defaults_to_one_second_refresh(self) -> None:
        args = build_parser().parse_args(["watch"])

        self.assertEqual(args.interval, DEFAULT_WATCH_INTERVAL)
        self.assertEqual(args.interval, 1.0)


class ElapsedBetweenTest(TestCase):
    def test_uses_end_timestamp_when_session_has_finished(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(
            elapsed_between(
                "2026-06-03T07:00:00+00:00",
                "2026-06-03T07:30:05+00:00",
                now,
            ),
            "00:30:05",
        )


class RenderSessionsTest(TestCase):
    def test_busy_session_uses_working_active_label(self) -> None:
        now = datetime.now(timezone.utc)
        session = {
            "id": "session-1",
            "command": ["codex"],
            "cwd": "/tmp/cli-monitor",
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": (now - timedelta(seconds=1)).isoformat(),
            "last_input_at": (now - timedelta(seconds=10)).isoformat(),
            "ended_at": None,
        }

        with (
            patch("cli_monitor.cli.read_sessions", return_value=[session]),
            patch("cli_monitor.cli.pid_alive", return_value=True),
        ):
            rows = session_rows(active_after=5)

        self.assertEqual(rows[0]["status"], "busy")
        self.assertEqual(rows[0]["active"], "working")
        self.assertTrue(rows[0]["idle_seconds"].isdigit())

    def test_rendered_columns_follow_tui_order(self) -> None:
        rows = [
            {
                "id": "session-1",
                "cli": "codex",
                "status": "busy",
                "project": "cli_monitor",
                "active": "00:00:01",
                "idle_seconds": "1",
                "pid": "123",
                "runtime": "00:10:00",
            }
        ]

        lines = render_sessions(rows, width=100)

        self.assertIn("CLI     STATE  PROJECT", lines[3])
        self.assertIn("LAST_ACTIVE     PID     RUNTIME", lines[3])
        self.assertIn("codex   busy   cli_monitor", lines[5])
        self.assertIn("00:00:01     123    00:10:00", lines[5])


class PruneSessionsTest(TestCase):
    def test_prunes_done_and_gone_sessions(self) -> None:
        sessions = [
            {"id": "done-1", "pid": 111, "ended_at": "2026-06-03T08:00:00+00:00"},
            {"id": "gone-1", "pid": 222, "ended_at": None},
            {"id": "busy-1", "pid": 333, "last_output_at": "2026-06-03T08:00:00+00:00"},
        ]

        with (
            patch("cli_monitor.cli.read_sessions", return_value=sessions),
            patch("cli_monitor.cli.pid_alive", side_effect=lambda pid: pid == 333),
            patch("cli_monitor.cli.delete_session") as delete_session,
        ):
            removed = prune_done_or_gone_sessions()

        self.assertEqual(removed, 2)
        delete_session.assert_any_call("done-1")
        delete_session.assert_any_call("gone-1")
        self.assertEqual(delete_session.call_count, 2)
