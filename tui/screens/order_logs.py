"""Order logs screen — shows market + completed order data in tabular form."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from tui.services.order_logs import OrderLogsPayload, OrderLogsService
from tui.widgets import ClockWidget


class DatePromptScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "Close")]

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="date-prompt-shell"):
            yield Static(" ORDER LOGS ▸ ENTER DATE ", classes="screen-title")
            with Horizontal(classes="form-row"):
                yield Static("Date (YYYY-MM-DD)", classes="form-label")
                yield Input(
                    value=self.initial,
                    placeholder="2026-04-15",
                    id="date-input",
                    classes="form-input",
                )
            yield Static("", id="date-prompt-status")
            with Horizontal():
                yield Button("[Enter] Load", id="submit", classes="action-button")
                yield Button("[Esc] Cancel", id="cancel", classes="action-button")

    def on_mount(self) -> None:
        self.query_one("#date-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        value = self.query_one("#date-input", Input).value.strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            self.query_one("#date-prompt-status", Static).update(
                "[#ff4757]Invalid date. Use YYYY-MM-DD.[/]"
            )
            return
        self.dismiss(value)


class OrderLogsScreen(Screen[None]):
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("t", "toggle_symbol", "Next Symbol"),
        ("k", "change_date", "Change Date"),
        ("escape", "app.pop_screen", "Back"),
    ]

    COLUMNS = (
        " BID QTY",
        " BID PRICE",
        " SPLITS",
        " ORDER QTY",
        " ORDER PRICE",
        " FETCH TIME",
        " END TIME",
    )

    def __init__(self, service: OrderLogsService | None = None) -> None:
        super().__init__()
        self.service = service or OrderLogsService()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.symbol_index = 0
        self.payload = OrderLogsPayload(symbols=[], rows_by_symbol={}, market_counts={}, completed_counts={})

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" ORDER LOGS ", classes="screen-title")
        yield ClockWidget(classes="panel-clock")
        with Vertical(id="order-logs-layout"):
            yield Static("", id="order-logs-header")
            table = DataTable(
                id="order-logs-table",
                zebra_stripes=True,
                cursor_foreground_priority="renderable",
                cursor_background_priority="css",
            )
            table.cursor_type = "row"
            yield table
            yield Static("", id="order-logs-status")
        with Horizontal(id="order-logs-actions"):
            yield Button("[R] Refresh", id="refresh", classes="action-button")
            yield Button("[T] Next Symbol", id="next-symbol", classes="action-button")
            yield Button("[K] Change Date", id="change-date", classes="action-button")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#order-logs-table", DataTable).add_columns(*self.COLUMNS)
        self._reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self.action_refresh()
        elif event.button.id == "next-symbol":
            self.action_toggle_symbol()
        elif event.button.id == "change-date":
            self.action_change_date()

    def action_refresh(self) -> None:
        self._reload()

    def action_toggle_symbol(self) -> None:
        if len(self.payload.symbols) < 2:
            return
        self.symbol_index = (self.symbol_index + 1) % len(self.payload.symbols)
        self._render_table()

    def action_change_date(self) -> None:
        self.app.push_screen(DatePromptScreen(self.date), self._on_date_selected)

    def _on_date_selected(self, date: str | None) -> None:
        if not date:
            return
        self.date = date
        self.symbol_index = 0
        self._reload()

    def _reload(self) -> None:
        self.payload = self.service.load(self.date)
        if self.symbol_index >= len(self.payload.symbols):
            self.symbol_index = 0
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one("#order-logs-table", DataTable)
        table.clear()

        header = self.query_one("#order-logs-header", Static)
        status = self.query_one("#order-logs-status", Static)

        if not self.payload.symbols:
            header.update(f"Date: [bold]{self.date}[/]  ·  No completed orders found.")
            status.update("")
            return

        symbol = self.payload.symbols[self.symbol_index]
        rows = self.payload.rows_by_symbol.get(symbol, [])

        for row in rows:
            cells = [
                row.bid_quantity,
                row.bid_price,
                row.splits,
                row.order_quantity,
                row.order_price,
                row.fetch_time,
                row.end_time,
            ]
            if row.highlight:
                cells = [f"[#3ddc84]{c}[/]" for c in cells]
            table.add_row(*cells)

        header.update(
            f"Date: [bold]{self.date}[/]  ·  Symbol: [bold #ff9e1b]{symbol}[/]  "
            f"({self.symbol_index + 1}/{len(self.payload.symbols)})"
        )
        status.update(
            f"{self.payload.market_counts.get(symbol, 0)} market tick(s) · "
            f"{self.payload.completed_counts.get(symbol, 0)} completed order(s)"
        )
