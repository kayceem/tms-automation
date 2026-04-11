"""Portfolio navigation and ATRAD order-book screens."""

from __future__ import annotations

import json
import time
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from tui.models import OrderBookRow
from tui.services.portfolio import PortfolioService


class PortfolioScreen(Screen[None]):
    BINDINGS = [
        ("up", "focus_previous_control", "Previous"),
        ("down", "focus_next_control", "Next"),
        ("a", "open_atrad", "ATRAD"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" PORTFOLIO ▸ PLATFORM SELECT ", classes="screen-title")
        yield Button("[A] ATRAD", id="atrad", classes="menu-button")
        yield Button("[ ] TMS (coming later)", id="tms", disabled=True, classes="menu-button")
        yield Button("[Esc] Back", id="back", classes="menu-button")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "atrad":
            self.action_open_atrad()
        elif event.button.id == "back":
            self.app.pop_screen()

    def on_mount(self) -> None:
        self.query_one("#atrad", Button).focus()

    def action_open_atrad(self) -> None:
        self.app.push_screen("atrad-users")

    def action_focus_next_control(self) -> None:
        self.focus_next(Button)

    def action_focus_previous_control(self) -> None:
        self.focus_previous(Button)


class ATRADUserSelectScreen(Screen[None]):
    BINDINGS = [
        ("j", "focus_next", "Next"),
        ("down", "focus_next", "Next"),
        ("k", "focus_previous", "Previous"),
        ("up", "focus_previous", "Previous"),
        ("enter", "activate_focused_user", "Open"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, service: PortfolioService | None = None) -> None:
        super().__init__()
        self.service = service or PortfolioService()
        self._user_paths_by_button_id: dict[str, Path] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" PORTFOLIO ▸ ATRAD ▸ SELECT ACCOUNT ", classes="screen-title")
        yield Static("", id="atrad-users-status")
        yield Footer()

    def on_mount(self) -> None:
        users = self.service.list_atrad_users()
        if not users:
            self.query_one("#atrad-users-status", Static).update("No ATRAD user files found.")
            return
        self._user_paths_by_button_id.clear()
        for index, path in enumerate(users, start=1):
            button_id = f"user_{index}"
            self._user_paths_by_button_id[button_id] = path
            self.mount(Button(path.stem, id=button_id, variant="primary", classes="menu-button"))
        self.query(Button).first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id in self._user_paths_by_button_id:
            path = self._user_paths_by_button_id[event.button.id]
            self.app.push_screen(OrderBookScreen(path, self.service))

    def action_focus_next(self) -> None:
        self.focus_next(Button)

    def action_focus_previous(self) -> None:
        self.focus_previous(Button)

    def action_activate_focused_user(self) -> None:
        focused = self.focused
        if isinstance(focused, Button) and focused.id and focused.id in self._user_paths_by_button_id:
            path = self._user_paths_by_button_id[focused.id]
            self.app.push_screen(OrderBookScreen(path, self.service))


class CancelConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        ("y", "confirm_cancel", "Confirm"),
        ("n", "dismiss(False)", "Close"),
        ("escape", "dismiss(False)", "Close"),
    ]

    def __init__(self, row: OrderBookRow, cancel_url: str) -> None:
        super().__init__()
        self.row = row
        self.cancel_url = cancel_url

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-shell"):
            yield Static(
                f" CONFIRM ▸ CANCEL {self.row.action} {self.row.security_code} ",
                classes="screen-title",
            )
            yield Static(
                "\n".join(
                    [
                        f"  client_order_id   : {self.row.client_order_id}",
                        f"  exchange_order_id : {self.row.exchange_order_id}",
                        f"  order_time        : {self.row.order_time}",
                        f"  cancel_url        : {self.cancel_url}",
                    ]
                )
            )
            with Horizontal():
                yield Button("[Y] Confirm Cancel", id="confirm", classes="action-button")
                yield Button("[N] Close", id="close", classes="action-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def on_mount(self) -> None:
        self.query_one("#confirm", Button).focus()

    def action_confirm_cancel(self) -> None:
        self.dismiss(True)


class OrderBookScreen(Screen[None]):
    BINDINGS = [
        ("r", "refresh_book", "Refresh"),
        ("c", "cancel_selected", "Cancel"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, user_path: Path, service: PortfolioService | None = None) -> None:
        super().__init__()
        self.user_path = user_path
        self.service = service or PortfolioService()
        self.rows: list[OrderBookRow] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" ATRAD ▸ ORDER BOOK ▸ {self.user_path.stem.upper()} ", classes="screen-title")
        table = DataTable(id="order-book-table")
        table.cursor_type = "row"
        yield table
        with Horizontal():
            yield Button("[R] Refresh", id="refresh", classes="action-button")
            yield Button("[C] Cancel Selected", id="cancel", classes="action-button")
            yield Button("[Esc] Back", id="back", classes="action-button")
        yield Static("", id="order-book-status")
        yield Static("", id="order-book-response")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#order-book-table", DataTable)
        table.add_columns(
            "order_id",
            "exchange_id",
            "symbol",
            "side",
            "qty",
            "filled",
            "remainder",
            "price",
            "amount",
            "status",
            "time",
            "last updated",
        )
        self.action_refresh_book()
        table.focus()

    def _set_status(self, message: str) -> None:
        self.query_one("#order-book-status", Static).update(message)

    def _set_response(self, message: str) -> None:
        self.query_one("#order-book-response", Static).update(message)

    @work(thread=True)
    def action_refresh_book(self) -> None:
        try:
            rows, payload = self.service.fetch_order_book(self.user_path)
        except RuntimeError as exc:
            self.app.call_from_thread(self._set_status, str(exc))
            return
        self.app.call_from_thread(self._apply_rows, rows, payload.get("lastUpdatedTime", ""))

    def _apply_rows(self, rows: list[OrderBookRow], last_updated_time: str) -> None:
        self.rows = rows
        table = self.query_one("#order-book-table", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                row.client_order_id,
                row.exchange_order_id,
                row.security_code,
                row.action,
                row.quantity,
                row.filled_quantity,
                row.remainder,
                row.price,
                row.amount,
                row.order_status,
                row.order_time,
                row.last_updated_time,
                key=row.client_order_id,
            )
        self._set_status(
            f"Loaded {len(rows)} order(s)"
            + (f" | last updated {last_updated_time}" if last_updated_time else "")
        )

    def _selected_row(self) -> OrderBookRow | None:
        table = self.query_one("#order-book-table", DataTable)
        if table.row_count == 0 or table.cursor_row < 0:
            return None
        row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
        if row_key is None:
            return None
        key = str(row_key.value)
        for row in self.rows:
            if row.client_order_id == key:
                return row
        return None

    def action_cancel_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self._set_status("Select an order first.")
            return
        cancel_url = self.service.build_cancel_url(self.user_path, row.raw)
        self.app.push_screen(
            CancelConfirmScreen(row, cancel_url),
            lambda confirmed: self._handle_cancel_result(row, confirmed),
        )

    @work(thread=True)
    def _cancel_and_refresh(self, row: OrderBookRow) -> None:
        try:
            result = self.service.cancel_order(self.user_path, row.raw)
        except RuntimeError as exc:
            self.app.call_from_thread(self._set_status, str(exc))
            return
        response_text = json.dumps(result, indent=2, sort_keys=True)
        self.app.call_from_thread(self._set_response, response_text)
        time.sleep(1)
        self.app.call_from_thread(
            self._set_status,
            f"Cancelled {row.security_code}. Refreshing...",
        )
        self.app.call_from_thread(self.action_refresh_book)

    def _handle_cancel_result(self, row: OrderBookRow, confirmed: bool) -> None:
        if confirmed:
            self._cancel_and_refresh(row)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self.action_refresh_book()
        elif event.button.id == "cancel":
            self.action_cancel_selected()
        elif event.button.id == "back":
            self.app.pop_screen()
