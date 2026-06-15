from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Static

from .cli import prune_done_or_gone_sessions, prunable_session_ids, session_rows
from .focus import focus_session_window


STATUS_STYLES = {
    "new": "bold #66d9ef",
    "busy": "bold #7bd88f",
    "wait": "bold #f0c36a",
    "done": "#7c8491",
    "gone": "bold #ff6b6b",
}
WAIT_HIGHLIGHT_SECONDS = 30
ATTENTION_HIGHLIGHT_STYLE = "#f6d58a on #3a2f16"


class ConfirmPruneScreen(ModalScreen[bool]):
    CSS = """
    ConfirmPruneScreen {
        align: center middle;
    }

    #confirm-prune-dialog {
        width: 56;
        height: auto;
        padding: 1 2;
        background: #151b22;
        border: thick #35506a;
    }

    #confirm-prune-title {
        text-style: bold;
        color: #e6edf3;
        margin-bottom: 1;
    }

    #confirm-prune-message {
        color: #d8dee9;
        margin-bottom: 1;
    }

    #confirm-prune-actions {
        height: auto;
        align-horizontal: center;
    }

    #confirm-prune-actions Button {
        width: 14;
        height: 3;
        margin: 0 1;
        border: none;
        background: #26313d;
        color: #e6edf3;
        text-style: none;
    }

    #confirm-prune-actions Button:hover {
        background: #2f4052;
    }

    #confirm-prune-actions Button:focus {
        background: #2f5f8f;
        color: #f5fbff;
        text-style: bold;
    }

    #confirm {
        color: #ffd7d7;
    }

    #confirm:focus {
        background: #8f3a3a;
        color: #ffffff;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Clean", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
        Binding("up", "focus_previous", "Previous", show=False),
        Binding("down", "focus_next", "Next", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, stale_count: int) -> None:
        super().__init__()
        self.stale_count = stale_count

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Clean done/gone sessions?", id="confirm-prune-title"),
            Static(
                f"This will delete {self.stale_count} done or gone session record(s).",
                id="confirm-prune-message",
            ),
            Horizontal(
                Button("OK (Y)", id="confirm"),
                Button("Cancel (N)", id="cancel"),
                id="confirm-prune-actions",
            ),
            id="confirm-prune-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_focus_previous(self) -> None:
        self._focus_button(-1)

    def action_focus_next(self) -> None:
        self._focus_button(1)

    def _focus_button(self, offset: int) -> None:
        buttons = list(self.query(Button))
        if not buttons:
            return
        focused = self.focused
        try:
            index = buttons.index(focused)
        except ValueError:
            index = 0
        buttons[(index + offset) % len(buttons)].focus()


class HighlightDataTable(DataTable[str]):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._highlight_row_styles: dict[object, Style] = {}

    def clear_highlights(self) -> None:
        self._highlight_row_styles.clear()
        self._clear_render_caches()
        self.refresh()

    def set_row_highlight(self, row_key: object, style: str) -> None:
        self._highlight_row_styles[row_key] = Style.parse(style)
        self._clear_render_caches()
        self.refresh()

    def _clear_render_caches(self) -> None:
        self._row_render_cache.clear()
        self._cell_render_cache.clear()
        self._line_cache.clear()

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        row_style = super()._get_row_style(row_index, base_style)
        if row_index == -1:
            return row_style
        row_key = self._row_locations.get_key(row_index)
        highlight_style = self._highlight_row_styles.get(row_key)
        if highlight_style is None:
            return row_style
        return row_style + highlight_style

    async def _on_click(self, event: events.Click) -> None:
        meta = event.style.meta
        if "row" not in meta or "column" not in meta:
            await super()._on_click(event)
            return

        row_index = meta["row"]
        column_index = meta["column"]
        is_header_click = self.show_header and row_index == -1
        is_row_label_click = self.show_row_labels and column_index == -1
        if is_header_click or is_row_label_click or meta.get("out_of_bounds", False):
            await super()._on_click(event)
            return

        coordinate = Coordinate(row_index, column_index)
        if not self.is_valid_coordinate(coordinate):
            await super()._on_click(event)
            return

        event.prevent_default()
        self._set_hover_cursor(True)
        self.cursor_coordinate = coordinate
        self._scroll_cursor_into_view(animate=True)
        if event.chain >= 2:
            self.post_message(
                DataTable.RowSelected(self, row_index, self._row_locations.get_key(row_index))
            )
        event.stop()


class SessionsApp(App[None]):
    CSS = """
    Screen {
        background: #0f1318;
    }

    #summary {
        height: 3;
        padding: 0 1;
        content-align: left middle;
        background: #151b22;
        color: #d8dee9;
        border-bottom: solid #35506a;
    }

    DataTable {
        height: 1fr;
        background: #0f1318;
        color: #d8dee9;
    }

    DataTable > .datatable--header {
        background: #1b222a;
        color: #e6edf3;
        text-style: bold;
    }

    DataTable > .datatable--odd-row {
        background: #0f1318;
    }

    DataTable > .datatable--even-row {
        background: #131a20;
    }

    DataTable > .datatable--cursor,
    DataTable:focus > .datatable--cursor {
        background: #2f5f8f;
        color: #f5fbff;
        text-style: bold;
    }

    DataTable > .datatable--hover {
        background: #243241;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "toggle_all", "All"),
        Binding("c", "prune", "Clean"),
        Binding("enter", "focus_session", "Focus"),
        Binding("space", "focus_session", "Focus", show=False),
    ]

    def __init__(self, active_after: int, interval: float, show_all: bool = False) -> None:
        super().__init__()
        self.active_after = active_after
        self.interval = max(0.25, interval)
        self.show_all = show_all
        self._rows_by_id: dict[str, dict[str, str]] = {}
        self.title = "cli-monitor"
        self.sub_title = self._mode_label

    @property
    def _mode_label(self) -> str:
        return "all sessions" if self.show_all else "live sessions"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="summary")
        table = HighlightDataTable(id="sessions", cursor_background_priority="css")
        table.cursor_type = "row"
        table.zebra_stripes = True
        yield table
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(HighlightDataTable)
        table.add_column("CLI")
        table.add_column("STATE")
        table.add_column("PROJECT")
        table.add_column("LAST_REPLY")
        table.add_column(Text("PID", justify="right"), width=7)
        table.add_column("LAST_ACTIVE")
        table.add_column("RUNTIME")
        self.refresh_sessions()
        self.set_interval(self.interval, self.refresh_sessions)

    def action_refresh(self) -> None:
        self.refresh_sessions()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.sub_title = self._mode_label
        self.refresh_sessions()

    def action_prune(self) -> None:
        stale_count = len(prunable_session_ids())
        if stale_count == 0:
            self.notify("No done or gone sessions to clean.", title="Clean")
            return

        self.push_screen(ConfirmPruneScreen(stale_count), self._prune_confirmed)

    def action_focus_session(self) -> None:
        table = self.query_one(HighlightDataTable)
        row_key = self._current_row_key(table)
        if row_key is None:
            self.notify("No session selected.", title="Focus")
            return
        self._focus_row_key(row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self._focus_row_key(event.row_key)

    def _focus_row_key(self, row_key: object) -> None:
        row_id = self._row_key_value(row_key)
        row = self._rows_by_id.get(row_id)
        if row is None:
            self.notify("Selected session is no longer visible.", title="Focus")
            return

        result = focus_session_window(row)
        severity = "information" if result.focused else "warning"
        self.notify(result.message, title="Focus", severity=severity)

    def _prune_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return

        removed = prune_done_or_gone_sessions()
        self.refresh_sessions()
        self.notify(f"Removed {removed} done or gone session(s).", title="Clean")

    def refresh_sessions(self) -> None:
        rows = session_rows(self.active_after, self.show_all)
        self._rows_by_id = {row["id"]: row for row in rows}
        table = self.query_one(HighlightDataTable)
        current_row_index = self._current_row_index(table)
        current_row_key = self._current_row_key(table)
        table.clear()
        table.clear_highlights()

        restored_row_index: int | None = None
        for row_index, row in enumerate(rows):
            highlight_style = self._row_highlight_style(row)
            row_key = table.add_row(
                self._cell_text(row["cli"]),
                self._status_text(row["status"], highlight_style),
                self._cell_text(row["project"]),
                self._cell_text(row["reply"]),
                self._cell_text(row["pid"], justify="right"),
                self._cell_text(row["active"]),
                self._cell_text(row["runtime"], justify="right"),
                key=row["id"],
            )
            if row_key == current_row_key:
                restored_row_index = row_index
            if highlight_style:
                table.set_row_highlight(row_key, highlight_style)

        self._restore_cursor(table, restored_row_index, current_row_index, len(rows))

        summary = self.query_one("#summary", Static)
        summary.update(self._summary_text(rows))

    def _current_row_index(self, table: HighlightDataTable) -> int | None:
        row_index = table.cursor_coordinate.row
        if row_index < 0 or row_index >= len(table.rows):
            return None
        return row_index

    def _current_row_key(self, table: HighlightDataTable) -> object | None:
        row_index = self._current_row_index(table)
        if row_index is None:
            return None
        try:
            return table._row_locations.get_key(row_index)
        except KeyError:
            return None

    def _row_key_value(self, row_key: object) -> str:
        value = getattr(row_key, "value", row_key)
        return "" if value is None else str(value)

    def _restore_cursor(
        self,
        table: HighlightDataTable,
        restored_row_index: int | None,
        previous_row_index: int | None,
        row_count: int,
    ) -> None:
        if row_count == 0:
            return
        if restored_row_index is not None:
            table.move_cursor(row=restored_row_index)
            return
        if previous_row_index is not None:
            table.move_cursor(row=min(previous_row_index, row_count - 1))

    def _cell_text(self, value: str, style: str = "", justify: str | None = None) -> Text:
        return Text(value, style=style, justify=justify, no_wrap=True)

    def _status_text(self, status: str, row_style: str = "") -> Text:
        style = row_style or STATUS_STYLES.get(status, "")
        return Text(status, style=style, no_wrap=True)

    def _row_highlight_style(self, row: dict[str, str]) -> str:
        if row["status"] == "new":
            return ATTENTION_HIGHLIGHT_STYLE
        if row["status"] != "wait":
            return ""
        try:
            idle_seconds = int(row.get("idle_seconds", ""))
        except ValueError:
            return ""
        if idle_seconds > WAIT_HIGHLIGHT_SECONDS:
            return ATTENTION_HIGHLIGHT_STYLE
        return ""

    def _summary_text(self, rows: list[dict[str, str]]) -> Text:
        counts: dict[str, int] = {}
        for row in rows:
            status = row["status"]
            counts[status] = counts.get(status, 0) + 1

        text = Text()
        mode = "all" if self.show_all else "live"
        text.append("sessions: ", style="bold")
        text.append(f"{mode} {len(rows)}", style="bold")
        text.append("\n")
        text.append(f"busy {counts.get('busy', 0)}", style=STATUS_STYLES["busy"])
        text.append(" - ")
        text.append(f"wait {counts.get('wait', 0)}", style=STATUS_STYLES["wait"])
        return text


def run_tui(active_after: int, interval: float, show_all: bool = False) -> int:
    SessionsApp(active_after, interval, show_all).run()
    return 0
