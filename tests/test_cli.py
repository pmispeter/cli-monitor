from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from cli_monitor.cli import (
    DEFAULT_WATCH_INTERVAL,
    build_parser,
    clock_time,
    display_status,
    elapsed_between,
    prune_done_or_gone_sessions,
    render_sessions,
    session_rows,
)
from cli_monitor.store import (
    Session,
    delete_session,
    is_suppressed_session,
    suppress_session,
    write_session,
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


class ClockTimeTest(TestCase):
    def test_shows_time_for_today(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 30, tzinfo=timezone.utc)
        value = datetime(2026, 6, 3, 8, 0, 1, tzinfo=timezone.utc).isoformat()

        self.assertEqual(
            clock_time(value, now),
            datetime(2026, 6, 3, 8, 0, 1, tzinfo=timezone.utc).astimezone().strftime("%H:%M:%S"),
        )

    def test_shows_date_and_time_for_previous_day(self) -> None:
        now = datetime(2026, 6, 3, 8, 0, 30, tzinfo=timezone.utc)
        value = datetime(2026, 6, 1, 8, 0, 1, tzinfo=timezone.utc).isoformat()

        self.assertEqual(
            clock_time(value, now),
            datetime(2026, 6, 1, 8, 0, 1, tzinfo=timezone.utc).astimezone().strftime("%m-%d %H:%M"),
        )


class RenderSessionsTest(TestCase):
    def test_busy_session_shows_reply_time_and_active_age(self) -> None:
        now = datetime.now(timezone.utc)
        last_output_at = (now - timedelta(seconds=1)).isoformat()
        session = {
            "id": "session-1",
            "command": ["codex"],
            "cwd": "/tmp/cli-monitor",
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": last_output_at,
            "last_input_at": (now - timedelta(seconds=10)).isoformat(),
            "ended_at": None,
        }

        with (
            patch("cli_monitor.cli.read_sessions", return_value=[session]),
            patch("cli_monitor.cli.pid_alive", return_value=True),
        ):
            rows = session_rows(active_after=5)

        self.assertEqual(rows[0]["status"], "busy")
        self.assertEqual(rows[0]["reply"], clock_time(last_output_at, now))
        self.assertEqual(rows[0]["active"], "00:00:01")
        self.assertTrue(rows[0]["idle_seconds"].isdigit())

    def test_wait_session_shows_reply_time_and_active_age(self) -> None:
        now = datetime.now(timezone.utc)
        last_output_at = (now - timedelta(seconds=30)).isoformat()
        session = {
            "id": "session-1",
            "command": ["codex"],
            "cwd": "/tmp/cli-monitor",
            "pid": 123,
            "started_at": (now - timedelta(seconds=60)).isoformat(),
            "last_output_at": last_output_at,
            "last_input_at": (now - timedelta(seconds=50)).isoformat(),
            "ended_at": None,
        }

        with (
            patch("cli_monitor.cli.read_sessions", return_value=[session]),
            patch("cli_monitor.cli.pid_alive", return_value=True),
        ):
            rows = session_rows(active_after=5)

        self.assertEqual(rows[0]["status"], "wait")
        self.assertEqual(rows[0]["reply"], clock_time(last_output_at, now))
        self.assertEqual(rows[0]["active"], "00:00:30")

    def test_rendered_columns_follow_tui_order(self) -> None:
        rows = [
            {
                "id": "session-1",
                "cli": "codex",
                "status": "busy",
                "project": "cli_monitor",
                "reply": "12:34:56",
                "active": "00:00:01",
                "idle_seconds": "1",
                "pid": "123",
                "runtime": "00:10:00",
            }
        ]

        lines = render_sessions(rows, width=100)

        self.assertIn("CLI     STATE  PROJECT", lines[3])
        self.assertIn("LAST_REPLY     PID LAST_ACTIVE     RUNTIME", lines[3])
        self.assertIn("codex   busy   cli_monitor", lines[5])
        self.assertIn("12:34:56     123    00:00:01    00:10:00", lines[5])


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


class SuppressedSessionsTest(TestCase):
    def test_suppressed_session_stays_hidden_after_wrapper_writes_it_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("cli_monitor.store.os.environ", {"XDG_STATE_HOME": tmp}):
                session = self._session("session-1", pid=123)
                write_session(session)
                suppress_session(session.id)

                write_session(session)

                with patch("cli_monitor.cli.pid_alive", return_value=True):
                    self.assertEqual(session_rows(active_after=5, show_all=True), [])

    def test_suppression_survives_refresh_before_wrapper_writes_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("cli_monitor.store.os.environ", {"XDG_STATE_HOME": tmp}):
                session = self._session("session-1", pid=123)
                write_session(session)
                suppress_session(session.id)
                delete_session(session.id)

                with patch("cli_monitor.cli.pid_alive", return_value=True):
                    self.assertEqual(session_rows(active_after=5, show_all=True), [])

                write_session(session)

                with patch("cli_monitor.cli.pid_alive", return_value=True):
                    self.assertEqual(session_rows(active_after=5, show_all=True), [])

    def test_prune_cleans_suppressed_gone_session_and_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("cli_monitor.store.os.environ", {"XDG_STATE_HOME": tmp}):
                session = self._session("session-1", pid=123)
                write_session(session)
                suppress_session(session.id)

                with patch("cli_monitor.cli.pid_alive", return_value=False):
                    removed = prune_done_or_gone_sessions()

                self.assertEqual(removed, 1)
                self.assertFalse(session.path.exists())
                self.assertFalse(is_suppressed_session(session.id))

    def test_prune_keeps_suppressed_live_session_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("cli_monitor.store.os.environ", {"XDG_STATE_HOME": tmp}):
                session = self._session("session-1", pid=123)
                write_session(session)
                suppress_session(session.id)

                with patch("cli_monitor.cli.pid_alive", return_value=True):
                    removed = prune_done_or_gone_sessions()

                self.assertEqual(removed, 0)
                self.assertTrue(session.path.exists())
                self.assertTrue(is_suppressed_session(session.id))

    def test_prune_keeps_orphaned_suppression_when_recorded_pid_is_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("cli_monitor.store.os.environ", {"XDG_STATE_HOME": tmp}):
                suppress_session("session-1", pid=123)

                with patch("cli_monitor.store.pid_alive", return_value=True):
                    removed = prune_done_or_gone_sessions()

                self.assertEqual(removed, 0)
                self.assertTrue(is_suppressed_session("session-1"))

    def test_prune_cleans_orphaned_suppression_when_recorded_pid_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("cli_monitor.store.os.environ", {"XDG_STATE_HOME": tmp}):
                suppress_session("session-1", pid=123)

                with patch("cli_monitor.store.pid_alive", return_value=False):
                    removed = prune_done_or_gone_sessions()

                self.assertEqual(removed, 0)
                self.assertFalse(is_suppressed_session("session-1"))

    def _session(self, session_id: str, pid: int) -> Session:
        now = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc).isoformat()
        return Session(
            id=session_id,
            pid=pid,
            command=["codex"],
            cwd="/tmp/cli-monitor",
            tty=None,
            started_at=now,
            updated_at=now,
            last_output_at=now,
            last_input_at=now,
        )
