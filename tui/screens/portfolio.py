"""Portfolio navigation and ATRAD order-book screens."""

from __future__ import annotations

import json
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static, TabbedContent, TabPane

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


class SymbolPromptScreen(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "dismiss(None)", "Close"),
    ]

    def __init__(self, title: str, submit_label: str = "Submit", initial: str = "") -> None:
        super().__init__()
        self.prompt_title = title
        self.submit_label = submit_label
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="symbol-prompt-shell"):
            yield Static(f" {self.prompt_title.upper()} ", classes="screen-title")
            with Horizontal(classes="form-row"):
                yield Static("Symbol", classes="form-label")
                yield Input(
                    value=self.initial,
                    placeholder="e.g. NABIL",
                    id="symbol-input",
                    classes="form-input",
                )
            yield Static("", id="symbol-prompt-status")
            with Horizontal():
                yield Button(f"[Enter] {self.submit_label}", id="submit", classes="action-button")
                yield Button("[Esc] Cancel", id="cancel", classes="action-button")

    def on_mount(self) -> None:
        self.query_one("#symbol-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        value = self.query_one("#symbol-input", Input).value.strip().upper()
        if not value:
            self.query_one("#symbol-prompt-status", Static).update("[#ff4757]Enter a symbol.[/]")
            return
        self.dismiss(value)


class OrderBookScreen(Screen[None]):
    BINDINGS = [
        ("ctrl+1", "show_active_panel", "Active"),
        ("ctrl+2", "show_completed_panel", "Completed"),
        ("ctrl+3", "show_watchlist_panel", "Watchlists"),
        ("ctrl+4", "show_market_panel", "Market"),
        ("s", "change_market_symbol", "Symbol"),
        ("k", "change_market_symbol", "Search Symbol"),
        ("left", "previous_panel", "Prev Panel"),
        ("right", "next_panel", "Next Panel"),
        ("r", "refresh_book", "Refresh"),
        ("c", "cancel_selected", "Cancel"),
        ("t", "cycle_watchlist", "Cycle Watchlist"),
        ("a", "add_symbol", "Add Symbol"),
        ("g", "clear_response", "Clear Response"),
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
        self._market_symbol: str | None = None
        self.user_label = self.service.get_user_label(self.user_path)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" ATRAD ▸ ORDER BOOK ▸ {self.user_label.upper()} ", classes="screen-title")
        with TabbedContent(initial="tab-active", id="portfolio-tabs"):
            with TabPane("Active", id="tab-active"):
                table = DataTable(
                    id="order-book-table",
                    zebra_stripes=True,
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
                table.cursor_type = "row"
                yield table

            with TabPane("Completed", id="tab-completed"):
                table = DataTable(
                    id="completed-order-book-table",
                    zebra_stripes=True,
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
                table.cursor_type = "row"
                yield table

            with TabPane("Watchlists", id="tab-watchlists"):
                watchlist_table = DataTable(
                    id="watchlist-table",
                    zebra_stripes=True,
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
                watchlist_table.cursor_type = "row"
                yield watchlist_table

            with TabPane("Market", id="tab-market"):
                with Horizontal(id="market-tables"):
                    bids_table = DataTable(
                        id="market-bids-table",
                        zebra_stripes=True,
                        cursor_foreground_priority="renderable",
                        cursor_background_priority="css",
                    )
                    bids_table.cursor_type = "row"
                    yield bids_table
                    asks_table = DataTable(
                        id="market-asks-table",
                        zebra_stripes=True,
                        cursor_foreground_priority="renderable",
                        cursor_background_priority="css",
                    )
                    asks_table.cursor_type = "row"
                    yield asks_table
                yield Static("", id="market-ltp", classes="market-ltp")
        yield Static("", id="portfolio-total")
        yield Static("", id="portfolio-status")
        with VerticalScroll(id="active-response-scroll", classes="response-scroll"):
            yield Static("", id="active-response", classes="response-text")
        with VerticalScroll(id="completed-response-scroll", classes="response-scroll"):
            yield Static("", id="completed-response", classes="response-text")
        with VerticalScroll(id="watchlist-response-scroll", classes="response-scroll"):
            yield Static("", id="watchlist-response", classes="response-text")
        with VerticalScroll(id="market-response-scroll", classes="response-scroll"):
            yield Static("", id="market-response", classes="response-text")
        with Horizontal(id="portfolio-actions"):
            yield Button("[R] Refresh", id="refresh", classes="action-button")
            yield Button("[C] Cancel Selected", id="cancel", classes="action-button")
            yield Static("", id="portfolio-actions-spacer")
            yield Select(
                [],
                prompt="Watchlist",
                id="watchlist-selector",
            )
        yield Footer()

    def on_mount(self) -> None:
        active_table = self.query_one("#order-book-table", DataTable)
        active_table.add_columns(
            "  SYMBOL",
            "   SIDE",
            "     QTY",
            "  FILLED",
            "    REM",
            "    PRICE",
            "     AMOUNT",
            " STATUS",
            "ORDER ID",
            "   EXCH ID",
            "  TIME",
            "  UPDATED",
        )
        completed_table = self.query_one("#completed-order-book-table", DataTable)
        completed_table.add_columns(
            "  SYMBOL",
            "   SIDE",
            "     QTY",
            "  FILLED",
            "    REM",
            "    PRICE",
            "     AMOUNT",
            " STATUS",
            "ORDER ID",
            "   EXCH ID",
            " TIME",
            "  UPDATED",
        )
        watchlist_table = self.query_one("#watchlist-table", DataTable)
        watchlist_table.add_columns(
            "  SYMBOL",
            "    LAST",
            "     CHG",
            "    CHG%",
            "    OPEN",
            "    HIGH",
            "     LOW",
            "  VOLUME",
            "   T/O",
            "          BID",
            "          ASK",
        )
        bids_table = self.query_one("#market-bids-table", DataTable)
        bids_table.add_columns("#", "splits", "qty", "bid price")
        asks_table = self.query_one("#market-asks-table", DataTable)
        asks_table.add_columns("#", "ask price", "qty", "splits")
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

    def action_show_market_panel(self) -> None:
        self._set_panel("tab-market")

    _PANELS = ("tab-active", "tab-completed", "tab-watchlists", "tab-market")

    def action_previous_panel(self) -> None:
        current = self._PANELS.index(self._active_panel())
        self._set_panel(self._PANELS[(current - 1) % len(self._PANELS)])

    def action_next_panel(self) -> None:
        current = self._PANELS.index(self._active_panel())
        self._set_panel(self._PANELS[(current + 1) % len(self._PANELS)])

    def _focus_current_panel(self) -> None:
        panel = self._active_panel()
        if panel == "tab-active":
            self.query_one("#order-book-table", DataTable).focus()
        elif panel == "tab-completed":
            self.query_one("#completed-order-book-table", DataTable).focus()
        elif panel == "tab-market":
            self.query_one("#market-bids-table", DataTable).focus()
        else:
            self.query_one("#watchlist-table", DataTable).focus()

    _PANEL_KEY = {
        "tab-active": "active",
        "tab-completed": "completed",
        "tab-watchlists": "watchlist",
        "tab-market": "market",
    }

    def _update_action_buttons(self) -> None:
        panel = self._active_panel()
        cancel_button = self.query_one("#cancel", Button)
        cancel_button.display = panel == "tab-active"
        selector = self.query_one("#watchlist-selector", Select)
        selector.display = panel == "tab-watchlists"
        for key in ("active", "completed", "watchlist", "market"):
            self.query_one(f"#{key}-response-scroll").display = self._PANEL_KEY.get(panel) == key

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self._focus_current_panel()
        self._update_action_buttons()
        if self._active_panel() == "tab-market" and self._market_symbol is None:
            self._prompt_market_symbol()

    def _set_status(self, message: str, panel: str = "active") -> None:
        panel_label = {
            "active": "Active",
            "completed": "Completed",
            "watchlists": "Watchlists",
            "market": "Market",
        }.get(panel, panel.title())
        self.query_one("#portfolio-status", Static).update(f"{panel_label}: {message}")

    def _set_response(self, message: str, panel: str = "active") -> None:
        key = "watchlist" if panel == "watchlists" else panel
        self.query_one(f"#{key}-response", Static).update(message)

    def action_clear_response(self) -> None:
        panel = self._PANEL_KEY.get(self._active_panel())
        if panel is None:
            return
        self.query_one(f"#{panel}-response", Static).update("")

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
                if int(str(row.filled_quantity)) > 0 and Decimal(row.price.replace(",", "")):
                    total += int(str(row.filled_quantity).replace(",", "")) * Decimal(str(row.price).replace(",", ""))
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
            if panel == "tab-market":
                if self._market_symbol is None:
                    self.app.call_from_thread(
                        self._set_status, "Press K to search a symbol.", "market",
                    )
                    return
                symbol = self._market_symbol
                ltp, market_details, last_updated_time = self.service.fetch_script_details(self.user_path, symbol)
                self.app.call_from_thread(self._apply_market, symbol, market_details, ltp, last_updated_time)
                return
            if not self._watchlists_loaded:
                watchlists = self.service.fetch_custom_watchlists(self.user_path)
                self.app.call_from_thread(self._apply_watchlists, watchlists)
                return
            if not self._selected_watchlist_id:
                self.app.call_from_thread(self._set_status, "No watchlist selected.", "watchlists")
                return
            watch_id = int(self._selected_watchlist_id)
            rows, last_updated_time = self.service.fetch_watchlist(self.user_path, watch_id)
            self.app.call_from_thread(self._apply_watchlist_rows, watch_id, rows, last_updated_time)
            return
        except RuntimeError as exc:
            panel_status = {
                "tab-active": "active",
                "tab-completed": "completed",
                "tab-watchlists": "watchlists",
                "tab-market": "market",
            }.get(panel, "active")
            self.app.call_from_thread(self._set_status, str(exc), panel_status)
            return

    _STATUS_PALETTE = {
        "filled": "#3ddc84",
        "fill": "#3ddc84",
        "complete": "#3ddc84",
        "completed": "#3ddc84",
        "executed": "#3ddc84",
        "pending": "#ffd166",
        "open": "#ffd166",
        "working": "#ffd166",
        "new": "#ffd166",
        "partial": "#ffd166",
        "partially": "#ffd166",
        "cancel": "#f47174",
        "cancelled": "#f47174",
        "canceled": "#f47174",
        "rejected": "#ff5c5c",
        "expired": "#6b6b6b",
    }

    @classmethod
    def _status_color(cls, status: str) -> str:
        key = (status or "").strip().lower()
        for token, color in cls._STATUS_PALETTE.items():
            if token in key:
                return color
        return "#e8e8e8"

    @staticmethod
    def _float_cell(value: str) -> float | None:
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return None

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
            action = (row.action or "").strip().upper()
            is_buy = action.startswith("B")
            is_sell = action.startswith("S")
            side_color = "#3ddc84" if is_buy else ("#f47174" if is_sell else "#e8e8e8")
            side_arrow = "▲" if is_buy else ("▼" if is_sell else "·")
            side_cell = f"[bold {side_color}]{side_arrow} {action or '-':<4}[/]"

            qty_f = self._float_cell(row.quantity)
            filled_f = self._float_cell(row.filled_quantity) or 0.0
            pct_filled = (filled_f / qty_f * 100) if qty_f and qty_f > 0 else None
            if filled_f > 0 and pct_filled is not None:
                fill_color = "#3ddc84" if pct_filled >= 100 else "#ffd166"
                filled_cell = f"[bold {fill_color}]{row.filled_quantity}[/] [#6b6b6b]({pct_filled:.0f}%)[/]"
            else:
                filled_cell = f"[#6b6b6b]{row.filled_quantity or '0':>8}[/]"

            rem_f = self._float_cell(row.remainder)
            if rem_f is not None and rem_f == 0:
                rem_cell = f"[#6b6b6b]{row.remainder:>6}[/]"
            else:
                rem_cell = f"[#e8e8e8]{row.remainder or '-':>6}[/]"

            status_color = self._status_color(row.order_status)
            status_cell = f"[bold {status_color}]{(row.order_status or '-').upper():<10}[/]"
            format_time = lambda t: t.split(" ")[-1] if t else "-"
            symbol_cell = f"[bold #5fd7ff]{row.security_code or '-'}[/]"
            qty_cell = f"[#e8e8e8]{(row.quantity or '-'):>8}[/]"
            price_cell = f"[bold #e8e8e8]{(row.price or '-'):>10}[/]"
            amount_cell = f"[#e8e8e8]{(row.amount or '-'):>12}[/]"
            order_id_cell = f"[#6b6b6b]{row.client_order_id or '-'}[/]"
            exch_cell = f"[#6b6b6b]{row.exchange_order_id or '-'}[/]"
            time_cell = f"[#6b6b6b]{format_time(row.order_time) or '-'}[/]"
            updated_cell = f"[#5fd7ff]{format_time(row.last_updated_time) or '-'}[/]"

            table.add_row(
                symbol_cell,
                side_cell,
                qty_cell,
                filled_cell,
                rem_cell,
                price_cell,
                amount_cell,
                status_cell,
                order_id_cell,
                exch_cell,
                time_cell,
                updated_cell,
                key=row.client_order_id,
            )
        self._set_total(rows, "Active" if panel == "active" else "Completed")
        self._set_status(
            f"{'Active' if panel == 'active' else 'Completed'} · {len(rows)} order(s)"
            + (f" · updated {last_updated_time}" if last_updated_time else ""),
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
            rows, last_updated_time = self.service.fetch_watchlist(self.user_path, watch_id)
        except RuntimeError as exc:
            self.app.call_from_thread(self._set_status, str(exc), "watchlists")
            return
        self.app.call_from_thread(self._apply_watchlist_rows, watch_id, rows, last_updated_time)

    @staticmethod
    def _watchlist_row_color(net: str, pct: str) -> str | None:
        try:
            n = float(str(net).replace(",", ""))
        except (ValueError, TypeError):
            return None
        try:
            p = abs(float(str(pct).replace("%", "").replace(",", "")))
        except (ValueError, TypeError):
            p = 0.0
        if n > 0:
            return "#62ff7a" if p > 9.9 else "#3ddc84"
        if n < 0:
            return "#ff5c5c" if p > 9.9 else "#f47174"
        return None

    def _apply_watchlist_rows(self, watch_id: int, rows: list[WatchlistEntryRow], last_updated_time: str) -> None:
        self.watchlist_rows = rows
        table = self.query_one("#watchlist-table", DataTable)
        table.clear()
        for row in rows:
            color = self._watchlist_row_color(row.net_change, row.percent_change)
            try:
                n = float(str(row.net_change).replace(",", ""))
            except (ValueError, TypeError):
                n = 0.0
            arrow = "▲" if n > 0 else ("▼" if n < 0 else "·")
            sign = "+" if n > 0 else ""

            def rjust(value: str, width: int) -> str:
                return str(value or "-").rjust(width)

            def tinted(text: str, bold: bool = False) -> str:
                if color is None:
                    return text
                prefix = "bold " if bold else ""
                return f"[{prefix}{color}]{text}[/]"

            def muted(text: str) -> str:
                return tinted(text) if color else f"[#6b6b6b]{text}[/]"

            symbol_cell = (
                f"[bold {color}]{row.security_code}[/]" if color else f"[bold #5fd7ff]{row.security_code}[/]"
            )
            last_cell = (
                f"[bold {color}]{rjust(row.last_price, 10)}[/]"
                if color
                else f"[bold #e8e8e8]{rjust(row.last_price, 10)}[/]"
            )
            chg_cell = tinted(f"{arrow} {sign}{row.net_change}".rjust(12), bold=True) if color else muted(rjust(row.net_change, 12))
            pct_cell = tinted(f"{sign}{row.percent_change}%".rjust(9), bold=True) if color else muted(rjust(row.percent_change, 9))

            bid_pair = (
                f"{row.bid_quantity} × {row.bid_price}"
                if row.bid_quantity not in ("-", "", None) and row.bid_price not in ("-", "", None)
                else "-"
            )
            ask_pair = (
                f"{row.ask_price} × {row.ask_quantity}"
                if row.ask_quantity not in ("-", "", None) and row.ask_price not in ("-", "", None)
                else "-"
            )
            bid_cell = f"[#00d26a]{bid_pair.rjust(14)}[/]" if bid_pair != "-" else muted(rjust("-", 14))
            ask_cell = f"[#ff4757]{ask_pair.rjust(14)}[/]" if ask_pair != "-" else muted(rjust("-", 14))

            table.add_row(
                symbol_cell,
                last_cell,
                chg_cell,
                pct_cell,
                muted(rjust(row.opening_price, 10)),
                f"[#00d26a]{rjust(row.high_price, 10)}[/]" if row.high_price not in ("-", "", None) else muted(rjust("-", 10)),
                f"[#ff4757]{rjust(row.low_price, 10)}[/]" if row.low_price not in ("-", "", None) else muted(rjust("-", 10)),
                muted(rjust(row.volume, 12)),
                muted(rjust(row.turnover, 14)),
                bid_cell,
                ask_cell,
                key=row.security_code,
            )
        self._set_status(
            f"Watchlist {watch_id} · {len(rows)} symbol(s) · updated {last_updated_time}",
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

    def action_cycle_watchlist(self) -> None:
        if not self.watchlists:
            self._set_status("No watchlists loaded.", "watchlists")
            return
        ids = [row.watch_list_id for row in self.watchlists]
        try:
            idx = ids.index(self._selected_watchlist_id) if self._selected_watchlist_id else -1
        except ValueError:
            idx = -1
        next_row = self.watchlists[(idx + 1) % len(self.watchlists)]
        selector = self.query_one("#watchlist-selector", Select)
        selector.value = next_row.watch_list_id
        self._open_watchlist_by_row(next_row)

    def action_add_symbol(self) -> None:
        if self._active_panel() != "tab-watchlists":
            return
        if not self._selected_watchlist_id:
            self._set_status("Select a watchlist first.", "watchlists")
            return
        row = next(
            (item for item in self.watchlists if item.watch_list_id == self._selected_watchlist_id),
            None,
        )
        if row is None:
            self._set_status("Watchlist not found.", "watchlists")
            return
        self.app.push_screen(
            SymbolPromptScreen(
                title=f"WATCHLIST ▸ ADD SYMBOL ▸ {row.watch_list_name}",
                submit_label="Add",
            ),
            lambda symbol: self._handle_add_symbol_result(row, symbol),
        )

    def _handle_add_symbol_result(self, row: CustomWatchlistRow, symbol: str | None) -> None:
        if not symbol:
            return
        try:
            watch_id = int(row.watch_list_id)
        except ValueError:
            self._set_status(f"Invalid watchlist ID: {row.watch_list_id}", "watchlists")
            return
        self._add_symbol(watch_id, symbol)

    @work(thread=True)
    def _add_symbol(self, watch_id: int, symbol: str) -> None:
        try:
            result = self.service.add_symbol_to_watchlist(self.user_path, watch_id, symbol)
        except RuntimeError as exc:
            self.app.call_from_thread(
                self._set_status, f"Add failed: {exc}", "watchlists",
            )
            return
        except Exception as exc:
            self.app.call_from_thread(
                self._set_status, f"Unexpected error: {exc}", "watchlists",
            )
            return
        self.app.call_from_thread(
            self._set_response, json.dumps(result, indent=2, sort_keys=True), "watchlist",
        )
        self.app.call_from_thread(
            self._set_status, f"Added {symbol} to watchlist. Refreshing...", "watchlists",
        )
        self.app.call_from_thread(self._load_watchlist, watch_id)

    def action_change_market_symbol(self) -> None:
        if self._active_panel() != "tab-market":
            return
        self._prompt_market_symbol()

    def _prompt_market_symbol(self) -> None:
        self.app.push_screen(
            SymbolPromptScreen(
                title="MARKET DETAILS ▸ ENTER SYMBOL",
                submit_label="Load",
                initial=self._market_symbol or "",
            ),
            self._handle_market_symbol_result,
        )

    def _handle_market_symbol_result(self, symbol: str | None) -> None:
        if not symbol:
            return
        self._market_symbol = symbol
        self.action_refresh_book()

    def _apply_market(self, symbol: str, details: dict, ltp: dict, last_updated_time: str) -> None:
        bids_table = self.query_one("#market-bids-table", DataTable)
        asks_table = self.query_one("#market-asks-table", DataTable)
        bids_table.clear()
        asks_table.clear()
        bids = details.get("bid", []) or []
        asks = details.get("ask", []) or []
        for i, b in enumerate(bids, start=1):
            bids_table.add_row(
                str(i),
                str(b.get("splits", "-")),
                str(b.get("qty", "-")),
                f"[#00d26a]{b.get('price', '-')}[/]",
            )
        bids_table.add_row(
            "[bold #ff9e1b]TOTAL[/]",
            "",
            f"[bold #00d26a]{details.get('totalbids', '0')}[/]",
            "",
        )
        for i, a in enumerate(asks, start=1):
            asks_table.add_row(
                str(i),
                f"[#ff4757]{a.get('price', '-')}[/]",
                str(a.get("qty", "-")),
                str(a.get("splits", "-")),
            )
        asks_table.add_row(
            "[bold #ff9e1b]TOTAL[/]",
            "",
            f"[bold #ff4757]{details.get('totalask', '0')}[/]",
            "",
        )
        self.query_one("#market-ltp", Static).update(self._format_ltp(ltp))
        self.query_one("#portfolio-total", Static).update("")
        self._set_status(
            f"{symbol} · LTP {ltp.get('tradeprice', '-')} · updated {last_updated_time}",
            "market",
        )

    @staticmethod
    def _float_or_none(value) -> float | None:
        try:
            return float(str(value).replace(",", "").replace("%", ""))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _format_ltp(cls, ltp: dict) -> str:
        security = ltp.get("security", "-")
        company = ltp.get("companyname", "-")
        asset = ltp.get("assetClass", "-")
        price = ltp.get("tradeprice", "-")
        net = ltp.get("netchange", "-")
        pct = ltp.get("perchange", "-")
        open_px = ltp.get("openingprice", "-")
        close = ltp.get("closingprice", "-")
        high = ltp.get("highpx", "-")
        low = ltp.get("lowpx", "-")
        volume = ltp.get("totvolume", "-")
        turnover = ltp.get("totturnover", "-")
        trades = ltp.get("tottrades", "-")
        size = ltp.get("tradesize", "-")
        w52h = ltp.get("week52High", "-")
        w52l = ltp.get("week52Low", "-")
        last_time = ltp.get("lasttradedtime", "-")
        odd_lot = ltp.get("oddLotQty", "-")

        net_val = cls._float_or_none(net) or 0.0
        color = "#00d26a" if net_val > 0 else ("#ff4757" if net_val < 0 else "#e8e8e8")
        arrow = "▲" if net_val > 0 else ("▼" if net_val < 0 else "●")
        sign = "+" if net_val > 0 else ""

        bar_width = 30
        range_bar = "─" * bar_width
        hi = cls._float_or_none(w52h)
        lo = cls._float_or_none(w52l)
        cur = cls._float_or_none(price)
        if hi is not None and lo is not None and cur is not None and hi > lo:
            pos = int(round(((cur - lo) / (hi - lo)) * (bar_width - 1)))
            pos = max(0, min(bar_width - 1, pos))
            range_bar = "[#7a4a00]" + "─" * pos + "[/][bold #ffd166]●[/][#7a4a00]" + "─" * (bar_width - 1 - pos) + "[/]"
        else:
            range_bar = f"[#7a4a00]{range_bar}[/]"

        def cell(label: str, value: str, value_color: str = "#e8e8e8", bold: bool = False) -> str:
            prefix = "bold " if bold else ""
            return f"[#5fd7ff]{label:<11}[/] [{prefix}{value_color}]{str(value):<14}[/]"

        lines = [
            f"[bold #ff9e1b]{security}[/]  [#6b6b6b]{company}[/]  [#1a1000 on #ffd166] {asset} [/]",
            "",
            f"[#5fd7ff]LAST[/]  [bold {color}]{price}[/]   [{color}]{arrow} {sign}{net} ({sign}{pct}%)[/]   [#5fd7ff]@[/] [#ffd166]{last_time}[/]",
            "",
            cell("Open", open_px) + "  " + cell("High", high, "#00d26a"),
            cell("Close", close) + "  " + cell("Low", low, "#ff4757"),
            "",
            cell("Volume", volume) + "  " + cell("Turnover", turnover),
            cell("Trades", trades) + "  " + cell("Trade Size", size),
            cell("Odd Lot", odd_lot),
            "",
            f"[#5fd7ff]52W Range[/]  [#ff4757]{w52l:>10}[/] {range_bar} [#00d26a]{w52h}[/]",
        ]
        return "\n".join(lines)

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
        self.app.call_from_thread(self._set_response, response_text, "active")
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
