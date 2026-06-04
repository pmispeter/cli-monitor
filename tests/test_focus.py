from __future__ import annotations

import tempfile
from pathlib import Path
from subprocess import CompletedProcess
from unittest import TestCase
from unittest.mock import patch

from cli_monitor.focus import (
    FocusResult,
    _activate_tmux_target,
    _candidate_pids,
    _open_tmux_attach_terminal,
    _terminal_attach_commands,
    _tmux_attach_script,
    _tmux_launch_context,
    _xprop_properties,
    focus_session_window,
)


class FocusSessionWindowTest(TestCase):
    def test_refuses_finished_sessions(self) -> None:
        result = focus_session_window({"status": "done", "pid": "123"})

        self.assertFalse(result.focused)
        self.assertIn("done", result.message)

    def test_focuses_recorded_window_with_xdotool(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], **_: object) -> CompletedProcess[str]:
            calls.append(command)
            if command == ["xdotool", "windowactivate", "--sync", "0x01"]:
                return CompletedProcess(command, 0, "", "")
            return CompletedProcess(command, 1, "", "")

        with (
            patch("cli_monitor.focus.shutil.which", side_effect=lambda name: name == "xdotool"),
            patch("cli_monitor.focus._candidate_pids", return_value=[123, 456]),
            patch("cli_monitor.focus.subprocess.run", side_effect=run),
        ):
            result = focus_session_window(
                {"status": "busy", "pid": "123", "tty": "/dev/pts/9", "window_id": "0x01"}
            )

        self.assertTrue(result.focused)
        self.assertIn(["xdotool", "windowactivate", "--sync", "0x01"], calls)

    def test_focuses_recorded_window_without_tab_restore(self) -> None:
        session = {
            "status": "busy",
            "pid": "123",
            "tty": "/dev/pts/9",
            "window_id": "0x01",
        }

        with (
            patch("cli_monitor.focus._candidate_pids", return_value=[123]),
            patch(
                "cli_monitor.focus._focus_recorded_window",
                return_value=FocusResult(True, "Focused recorded window."),
            ) as focus_recorded,
        ):
            result = focus_session_window(session)

        self.assertTrue(result.focused)
        self.assertEqual(result.message, "Focused recorded window.")
        focus_recorded.assert_called_once_with(session)

    def test_focuses_tmux_target_after_recorded_window(self) -> None:
        session = {
            "status": "busy",
            "pid": "123",
            "tty": "/dev/pts/9",
            "window_id": "0x01",
            "tmux_window_id": "@4",
            "tmux_pane_id": "%9",
        }

        with (
            patch("cli_monitor.focus._candidate_pids", return_value=[123]),
            patch(
                "cli_monitor.focus._focus_recorded_window",
                return_value=FocusResult(True, "Focused recorded window."),
            ) as focus_recorded,
            patch("cli_monitor.focus._activate_tmux_target", return_value=True) as activate_tmux,
        ):
            result = focus_session_window(session)

        self.assertTrue(result.focused)
        self.assertEqual(result.message, "Focused terminal window and tmux target.")
        focus_recorded.assert_called_once_with(session)
        activate_tmux.assert_called_once_with(session)

    def test_opens_terminal_for_tmux_when_no_existing_window_matches(self) -> None:
        session = {
            "status": "busy",
            "pid": "123",
            "tty": "/dev/pts/9",
            "tmux_socket": "/tmp/tmux-1000/default",
            "tmux_session_id": "$1",
            "tmux_window_id": "@4",
            "tmux_pane_id": "%9",
        }

        with (
            patch("cli_monitor.focus._candidate_pids", return_value=[123]),
            patch(
                "cli_monitor.focus._focus_recorded_window",
                return_value=FocusResult(False, "No recorded window found."),
            ),
            patch(
                "cli_monitor.focus._focus_with_xdotool",
                return_value=FocusResult(False, "xdotool found no matching window."),
            ),
            patch(
                "cli_monitor.focus.shutil.which",
                side_effect=lambda name: (
                    f"/usr/bin/{name}"
                    if name in {"xdotool", "tmux", "gnome-terminal"}
                    else None
                ),
            ),
            patch("cli_monitor.focus.subprocess.Popen") as popen,
        ):
            result = focus_session_window(session)

        self.assertTrue(result.focused)
        self.assertEqual(result.message, "Opened a new terminal attached to tmux target.")
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0][0:3], ["gnome-terminal", "--", "sh"])


class CandidatePidTest(TestCase):
    def test_candidates_include_session_ancestors_and_tty_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = Path(tmp)
            self._write_stat(proc_root, 100, 90)
            self._write_stat(proc_root, 90, 80)
            self._write_stat(proc_root, 80, 1)
            self._write_stat(proc_root, 200, 190)
            self._write_stat(proc_root, 190, 1)
            tty = proc_root / "pts" / "9"
            tty.parent.mkdir()
            tty.touch()
            fd_dir = proc_root / "200" / "fd"
            fd_dir.mkdir()
            (fd_dir / "0").symlink_to(tty)

            self.assertEqual(
                _candidate_pids(100, str(tty), proc_root),
                [100, 90, 80, 200, 190],
            )

    def _write_stat(self, proc_root: Path, pid: int, parent_pid: int) -> None:
        process_dir = proc_root / str(pid)
        process_dir.mkdir()
        (process_dir / "stat").write_text(
            f"{pid} (process {pid}) S {parent_pid} 0 0 0\n",
            encoding="utf-8",
        )


class XpropPropertiesTest(TestCase):
    def test_strips_property_type_from_name(self) -> None:
        output = "\n".join(
            [
                'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"',
                'WM_WINDOW_ROLE(STRING) = "gnome-terminal-window-abc"',
                '_GTK_WINDOW_OBJECT_PATH(UTF8_STRING) = "/org/gnome/Terminal/window/2"',
                '_GTK_UNIQUE_BUS_NAME(UTF8_STRING) = ":1.117"',
                '_GTK_APPLICATION_ID(UTF8_STRING) = "org.gnome.Terminal"',
            ]
        )

        with (
            patch("cli_monitor.focus.shutil.which", return_value=True),
            patch(
                "cli_monitor.focus.subprocess.run",
                return_value=CompletedProcess(["xprop"], 0, output, ""),
            ),
        ):
            properties = _xprop_properties("0x01")

        self.assertEqual(properties["WM_CLASS"], "Gnome-terminal")
        self.assertEqual(properties["WM_WINDOW_ROLE"], "gnome-terminal-window-abc")
        self.assertEqual(properties["_GTK_WINDOW_OBJECT_PATH"], "/org/gnome/Terminal/window/2")
        self.assertEqual(properties["_GTK_UNIQUE_BUS_NAME"], ":1.117")
        self.assertEqual(properties["_GTK_APPLICATION_ID"], "org.gnome.Terminal")


class TmuxContextTest(TestCase):
    def test_captures_tmux_ids_for_current_pane(self) -> None:
        output = "$1\twork\t@4\t2\t%9\t1\n"

        with (
            patch.dict(
                "cli_monitor.focus.os.environ",
                {"TMUX": "/tmp/tmux-1000/default,123,0", "TMUX_PANE": "%9"},
                clear=True,
            ),
            patch("cli_monitor.focus.shutil.which", return_value=True),
            patch(
                "cli_monitor.focus.subprocess.run",
                return_value=CompletedProcess(["tmux"], 0, output, ""),
            ),
        ):
            context = _tmux_launch_context()

        self.assertEqual(context["tmux_pane"], "%9")
        self.assertEqual(context["tmux_socket"], "/tmp/tmux-1000/default")
        self.assertEqual(context["tmux_session_id"], "$1")
        self.assertEqual(context["tmux_session_name"], "work")
        self.assertEqual(context["tmux_window_id"], "@4")
        self.assertEqual(context["tmux_window_index"], "2")
        self.assertEqual(context["tmux_pane_id"], "%9")
        self.assertEqual(context["tmux_pane_index"], "1")

    def test_activates_tmux_window_and_pane(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], **_: object) -> CompletedProcess[str]:
            calls.append(command)
            return CompletedProcess(command, 0, "", "")

        with (
            patch("cli_monitor.focus.shutil.which", return_value=True),
            patch("cli_monitor.focus.subprocess.run", side_effect=run),
        ):
            changed = _activate_tmux_target(
                {
                    "tmux_socket": "/tmp/tmux-1000/default",
                    "tmux_window_id": "@4",
                    "tmux_pane_id": "%9",
                }
            )

        self.assertTrue(changed)
        self.assertEqual(
            calls,
            [
                ["tmux", "-S", "/tmp/tmux-1000/default", "select-window", "-t", "@4"],
                ["tmux", "-S", "/tmp/tmux-1000/default", "select-pane", "-t", "%9"],
            ],
        )

    def test_builds_tmux_attach_script_with_recorded_target(self) -> None:
        script = _tmux_attach_script(
            {
                "tmux_socket": "/tmp/tmux-1000/default",
                "tmux_window_id": "@4",
                "tmux_pane_id": "%9",
            },
            "$1",
        )

        self.assertEqual(
            script,
            "tmux -S /tmp/tmux-1000/default select-window -t @4; "
            "tmux -S /tmp/tmux-1000/default select-pane -t %9; "
            "exec tmux -S /tmp/tmux-1000/default attach-session -t '$1'",
        )

    def test_opens_first_available_terminal_for_tmux_attach(self) -> None:
        launched: list[list[str]] = []

        def popen(command: list[str], **_: object) -> object:
            launched.append(command)
            return object()

        with (
            patch(
                "cli_monitor.focus.shutil.which",
                side_effect=lambda name: (
                    f"/usr/bin/{name}" if name in {"tmux", "xterm"} else None
                ),
            ),
            patch("cli_monitor.focus.subprocess.Popen", side_effect=popen),
        ):
            result = _open_tmux_attach_terminal(
                {
                    "tmux_session_name": "work",
                    "tmux_window_id": "@4",
                    "tmux_pane_id": "%9",
                }
            )

        self.assertTrue(result.focused)
        self.assertEqual(launched[0][0:4], ["xterm", "-e", "sh", "-lc"])

    def test_lists_only_available_terminal_attach_commands(self) -> None:
        with patch(
            "cli_monitor.focus.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}" if name == "kitty" else None,
        ):
            commands = _terminal_attach_commands("exec tmux attach")

        self.assertEqual(commands, [["kitty", "sh", "-lc", "exec tmux attach"]])
