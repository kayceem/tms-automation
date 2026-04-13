"""Portfolio navigation and ATRAD order-book screens."""

from __future__ import annotations

import json
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Select, Static, TabbedContent, TabPane

from tui.models import CustomWatchlistRow, OrderBookRow, WatchlistEntryRow
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
        with Vertical(classes="menu-shell"):
            yield Static(" PORTFOLIO ▸ PLATFORM SELECT ", classes="screen-title")
            yield Static("Choose the broker view to inspect live books. Use [bold]Esc[/] to go back.", classes="menu-subtitle")
            with Vertical(classes="menu-section"):
                with Vertical(classes="menu-list"):
                    yield Button(
                        "[bold #ff9e1b]A[/]  ATRAD  [#6b6b6b]Account selector and live order book[/]",
                        id="atrad",
                        classes="menu-item",
                    )
                    yield Static("─" * 64, classes="menu-divider")
                    yield Button(
                        "   TMS    [#6b6b6b]Not wired yet[/]",
                        id="tms",
                        disabled=True,
                        classes="menu-item",
                    )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "atrad":
            self.action_open_atrad()

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
        with Vertical(classes="menu-shell"):
            yield Static(" PORTFOLIO ▸ ATRAD ▸ SELECT ACCOUNT ", classes="screen-title")
            yield Static("Open a specific ATRAD account and inspect its live book. Use [bold]Esc[/] to go back.", classes="menu-subtitle")
            yield Static("", id="atrad-users-status")
            yield Vertical(classes="menu-section", id="atrad-users-list")
        yield Footer()

    def on_mount(self) -> None:
        users = self.service.list_atrad_users()
        if not users:
            self.query_one("#atrad-users-status", Static).update("No ATRAD user files found.")
            return
        users_list = self.query_one("#atrad-users-list", Vertical)
        self._user_paths_by_button_id.clear()
        for index, path in enumerate(users, start=1):
            button_id = f"user_{index}"
            self._user_paths_by_button_id[button_id] = path
            user_label = self.service.get_user_label(path)
            users_list.mount(
                Button(
                    f"[bold #ff9e1b]{index:02d}[/]  {user_label}  [#6b6b6b]{path.name}[/]",
                    id=button_id,
                    classes="menu-item",
                )
            )
            if index != len(users):
                users_list.mount(Static("─" * 64, classes="menu-divider"))
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
        ("ctrl+1", "show_active_panel", "Active"),
        ("ctrl+2", "show_completed_panel", "Completed"),
        ("ctrl+3", "show_watchlist_panel", "Watchlists"),
        ("left", "previous_panel", "Prev Panel"),
        ("right", "next_panel", "Next Panel"),
        ("r", "refresh_book", "Refresh"),
        ("c", "cancel_selected", "Cancel"),
        ("enter", "open_selected_watchlist", "Open Watchlist"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, user_path: Path, service: PortfolioService | None = None) -> None:
        super().__init__()
        self.user_path = user_path
        self.service = service or PortfolioService()
        self.rows: list[OrderBookRow] = []
        self.completed_rows: list[OrderBookRow] = []
        self.watchlists: list[CustomWatchlistRow] = []
        self.watchlist_rows: list[WatchlistEntryRow] = []
        self._watchlists_loaded = False
        self._selected_watchlist_id: str | None = None
        self.user_label = self.service.get_user_label(self.user_path)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" ATRAD ▸ ORDER BOOK ▸ {self.user_label.upper()} ", classes="screen-title")
        with TabbedContent(initial="tab-active", id="portfolio-tabs"):
            with TabPane("Active", id="tab-active"):
                table = DataTable(
                    id="order-book-table",
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
                table.cursor_type = "row"
                yield table

            with TabPane("Completed", id="tab-completed"):
                table = DataTable(
                    id="completed-order-book-table",
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
                table.cursor_type = "row"
                yield table

            with TabPane("Watchlists", id="tab-watchlists"):
                with Horizontal():
                    yield Static("Watchlist", classes="form-label")
                    yield Select(
                        [],
                        prompt="Select watchlist",
                        id="watchlist-selector",
                    )
                watchlist_table = DataTable(
                    id="watchlist-table",
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
                watchlist_table.cursor_type = "row"
                yield watchlist_table
        yield Static("", id="portfolio-total")
        yield Static("", id="portfolio-status")
        yield Static("", id="order-book-response")
        with Horizontal(id="portfolio-actions"):
            yield Button("[R] Refresh", id="refresh", classes="action-button")
            yield Button("[C] Cancel Selected", id="cancel", classes="action-button")
        yield Footer()

    def on_mount(self) -> None:
        active_table = self.query_one("#order-book-table", DataTable)
        active_table.add_columns(
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
        completed_table = self.query_one("#completed-order-book-table", DataTable)
        completed_table.add_columns(
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
        watchlist_table = self.query_one("#watchlist-table", DataTable)
        watchlist_table.add_columns(
            "symbol",
            "bid qty",
            "bid",
            "ask qty",
            "ask",
            "net",
            "%",
            "ltp",
            "last trade",
            "open",
            "high",
            "low",
            "volume",
            "turnover",
        )
        self.action_show_active_panel()
        active_table.focus()
        self._update_action_buttons()

    def _active_panel(self) -> str:
        return self.query_one("#portfolio-tabs", TabbedContent).active

    def _set_panel(self, panel_id: str) -> None:
        tabs = self.query_one("#portfolio-tabs", TabbedContent)
        tabs.active = panel_id
        self._focus_current_panel()
        self._update_action_buttons()
        self.action_refresh_book()

    def action_show_active_panel(self) -> None:
        self._set_panel("tab-active")

    def action_show_completed_panel(self) -> None:
        self._set_panel("tab-completed")

    def action_show_watchlist_panel(self) -> None:
        self._set_panel("tab-watchlists")

    def action_previous_panel(self) -> None:
        panels = ["tab-active", "tab-completed", "tab-watchlists"]
        current = panels.index(self._active_panel())
        self._set_panel(panels[(current - 1) % len(panels)])

    def action_next_panel(self) -> None:
        panels = ["tab-active", "tab-completed", "tab-watchlists"]
        current = panels.index(self._active_panel())
        self._set_panel(panels[(current + 1) % len(panels)])

    def _focus_current_panel(self) -> None:
        panel = self._active_panel()
        if panel == "tab-active":
            self.query_one("#order-book-table", DataTable).focus()
        elif panel == "tab-completed":
            self.query_one("#completed-order-book-table", DataTable).focus()
        else:
            self.query_one("#watchlist-selector", Select).focus()

    def _update_action_buttons(self) -> None:
        cancel_button = self.query_one("#cancel", Button)
        cancel_button.disabled = self._active_panel() != "tab-active"

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self._focus_current_panel()
        self._update_action_buttons()

    def _set_status(self, message: str, panel: str = "active") -> None:
        panel_label = {
            "active": "Active",
            "completed": "Completed",
            "watchlists": "Watchlists",
        }[panel]
        self.query_one("#portfolio-status", Static).update(f"{panel_label}: {message}")

    def _set_response(self, message: str) -> None:
        self.query_one("#order-book-response", Static).update(message)

    @staticmethod
    def _styled_cell(value: str, color: str) -> str:
        return f"[{color}]{value or '-'}[/]"

    def _set_total(self, rows: list[OrderBookRow], label: str) -> None:
        total = Decimal("0")
        has_value = False
        for row in rows:
            try:
                total += Decimal(str(row.amount).replace(",", ""))
                has_value = True
            except (InvalidOperation, TypeError, ValueError):
                continue

        total_text = f"{total:,.2f}" if has_value else "-"
        self.query_one("#portfolio-total", Static).update(f"{label} total amount: {total_text}")

    @work(thread=True)
    def action_refresh_book(self) -> None:
        panel = self._active_panel()
        try:
            if panel == "tab-active":
                rows, payload = self.service.fetch_order_book(self.user_path)
                self.app.call_from_thread(
                    self._apply_order_rows,
                    rows,
                    payload.get("lastUpdatedTime", ""),
                    "#order-book-table",
                    "active",
                )
                return
            if panel == "tab-completed":
                rows, payload = self.service.fetch_order_book(self.user_path, completed=True)
                self.app.call_from_thread(
                    self._apply_order_rows,
                    rows,
                    payload.get("lastUpdatedTime", ""),
                    "#completed-order-book-table",
                    "completed",
                )
                return
            if not self._watchlists_loaded:
                watchlists = self.service.fetch_custom_watchlists(self.user_path)
                self.app.call_from_thread(self._apply_watchlists, watchlists)
                return
            if not self._selected_watchlist_id:
                self.app.call_from_thread(self._set_status, "No watchlist selected.", "watchlists")
                return
            watch_id = int(self._selected_watchlist_id)
            rows = self.service.fetch_watchlist(self.user_path, watch_id)
            self.app.call_from_thread(self._apply_watchlist_rows, watch_id, rows)
            return
        except RuntimeError as exc:
            self.app.call_from_thread(
                self._set_status,
                str(exc),
                "watchlists" if panel == "tab-watchlists" else ("completed" if panel == "tab-completed" else "active"),
            )
            return

    def _apply_order_rows(
        self,
        rows: list[OrderBookRow],
        last_updated_time: str,
        table_id: str,
        panel: str,
    ) -> None:
        if panel == "active":
            self.rows = rows
        else:
            self.completed_rows = rows
        table = self.query_one(table_id, DataTable)
        table.clear()
        for row in rows:
            row_color = "#00d26a" if self._has_fill(row.filled_quantity) else "#ff4757"
            table.add_row(
                self._styled_cell(row.client_order_id, row_color),
                self._styled_cell(row.exchange_order_id, row_color),
                f"[bold #5fd7ff]{row.security_code}[/]",
                self._styled_cell(row.action, row_color),
                self._styled_cell(row.quantity, row_color),
                self._styled_cell(row.filled_quantity, row_color),
                self._styled_cell(row.remainder, row_color),
                self._styled_cell(row.price, row_color),
                self._styled_cell(row.amount, row_color),
                self._styled_cell(row.order_status, row_color),
                self._styled_cell(row.order_time, row_color),
                f"[bold #5fd7ff]{row.last_updated_time or '-'}[/]",
                key=row.client_order_id,
            )
        self._set_total(rows, "Active" if panel == "active" else "Completed")
        self._set_status(
            f"Loaded {len(rows)} order(s)"
            + (f" | last updated {last_updated_time}" if last_updated_time else "")
            ,
            panel,
        )

    def _apply_watchlists(self, watchlists: list[CustomWatchlistRow]) -> None:
        self.watchlists = watchlists
        self._watchlists_loaded = True
        selector = self.query_one("#watchlist-selector", Select)
        selector.set_options(
            [
                (f"{row.watch_list_name}", row.watch_list_id)
                for row in watchlists
            ]
        )
        self.watchlist_rows = []
        if watchlists:
            self._selected_watchlist_id = watchlists[0].watch_list_id
            selector.value = watchlists[0].watch_list_id
            self.query_one("#portfolio-total", Static).update("")
            self._set_status(f"Loaded {len(watchlists)} watchlist(s).", "watchlists")
            self._open_watchlist_by_row(watchlists[0])
        else:
            self.query_one("#portfolio-total", Static).update("")
            self._set_status("No custom watchlists found.", "watchlists")

    @staticmethod
    def _has_fill(filled_quantity: str) -> bool:
        try:
            return Decimal(str(filled_quantity).replace(",", "")) > 0
        except (InvalidOperation, TypeError, ValueError):
            return False

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

    @work(thread=True)
    def _load_watchlist(self, watch_id: int) -> None:
        try:
            rows = self.service.fetch_watchlist(self.user_path, watch_id)
        except RuntimeError as exc:
            self.app.call_from_thread(self._set_status, str(exc), "watchlists")
            return
        self.app.call_from_thread(self._apply_watchlist_rows, watch_id, rows)

    def _apply_watchlist_rows(self, watch_id: int, rows: list[WatchlistEntryRow]) -> None:
        self.watchlist_rows = rows
        table = self.query_one("#watchlist-table", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                f"[bold #5fd7ff]{row.security_code}[/]",
                row.bid_quantity,
                row.bid_price,
                row.ask_quantity,
                row.ask_price,
                row.net_change,
                row.percent_change,
                row.last_price,
                row.last_traded_time,
                row.opening_price,
                row.high_price,
                row.low_price,
                row.volume,
                row.turnover,
                key=row.security_code,
            )
        self._set_status(
            f"Loaded watchlist {watch_id} with {len(rows)} symbol(s).",
            "watchlists",
        )
        self.query_one("#portfolio-total", Static).update("")

    def _open_watchlist_by_row(self, row: CustomWatchlistRow) -> None:
        try:
            watch_id = int(row.watch_list_id)
        except ValueError:
            self._set_status(f"Invalid watchlist ID: {row.watch_list_id}", "watchlists")
            return
        self._selected_watchlist_id = row.watch_list_id
        self._load_watchlist(watch_id)

    def action_open_selected_watchlist(self) -> None:
        if self._active_panel() != "tab-watchlists":
            return
        row = next(
            (item for item in self.watchlists if item.watch_list_id == self._selected_watchlist_id),
            None,
        )
        if row is None:
            self._set_status("Select a watchlist first.", "watchlists")
            return
        self._open_watchlist_by_row(row)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "watchlist-selector":
            return
        if event.value in (None, Select.BLANK):
            return
        self._selected_watchlist_id = str(event.value)
        row = next(
            (item for item in self.watchlists if item.watch_list_id == self._selected_watchlist_id),
            None,
        )
        if row is not None:
            self._open_watchlist_by_row(row)

    def action_cancel_selected(self) -> None:
        if self._active_panel() != "tab-active":
            return
        row = self._selected_row()
        if row is None:
            self._set_status("Select an order first.", "active")
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
            self.app.call_from_thread(self._set_status, str(exc), "active")
            return
        response_text = json.dumps(result, indent=2, sort_keys=True)
        self.app.call_from_thread(self._set_response, response_text)
        time.sleep(1)
        self.app.call_from_thread(
            self._set_status,
            f"Cancelled {row.security_code}. Refreshing...",
            "active",
        )
        self.app.call_from_thread(self.action_show_active_panel)
        self.app.call_from_thread(self.action_refresh_book)

    def _handle_cancel_result(self, row: OrderBookRow, confirmed: bool) -> None:
        if confirmed:
            self._cancel_and_refresh(row)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self.action_refresh_book()
        elif event.button.id == "cancel":
            self.action_cancel_selected()
