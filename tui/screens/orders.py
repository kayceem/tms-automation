"""Order management screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual import work
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from tui.services.orders import OrderStoreService
from tui.services.price_updates import OrderPriceRefreshService
from tui.widgets import ClockWidget


ORDER_TEMPLATE = {
    "id": "new-order",
    "ticker": "NABIL",
    "price": 500,
    "quantity": 10,
    "base_quantity": 10,
    "queue_id": 1,
    "mode": "normal",
    "execute": False,
    "success": False,
}

MODE_OPTIONS = [
    ("normal", "normal"),
    ("ipo", "ipo"),
    ("ipo-trigger", "ipo-trigger"),
    ("ipo-trigger-low", "ipo-trigger-low"),
    ("trigger-sell", "trigger-sell"),
    ("ipo-sell-buy-trigger", "ipo-sell-buy-trigger"),
]

TIME_OPTIONS = [
    ("10:55:00", "10:55:00"),
    ("10:59:00", "10:59:00"),
    ("11:00:05", "11:00:05"),
    ("11:00:10", "11:00:10"),
]

JUST_BUY_PRESETS: dict[str, dict] = {
    "fast-no-fade": {
        "label": "Fast No Fade",
        "just_buy_pre_wait_ms": 1500,
        "just_buy_interval_ms": 10,
        "just_buy_max_requests": 400,
        "just_buy_fade_interval_ms": None,
        "just_buy_fade_timeout": None,
    },
    "fast-fade": {
        "label": "Fast Fade",
        "just_buy_pre_wait_ms": 1500,
        "just_buy_interval_ms": 10,
        "just_buy_max_requests": 400,
        "just_buy_fade_interval_ms": 40,
        "just_buy_fade_timeout": 60,
    },
    "no-fade": {
        "label": "No Fade",
        "just_buy_pre_wait_ms": 2000,
        "just_buy_interval_ms": 20,
        "just_buy_max_requests": 400,
        "just_buy_fade_interval_ms": None,
        "just_buy_fade_timeout": None,
    },
    "fade": {
        "label": "Fade",
        "just_buy_pre_wait_ms": 2000,
        "just_buy_interval_ms": 20,
        "just_buy_max_requests": 400,
        "just_buy_fade_interval_ms": 40,
        "just_buy_fade_timeout": 60,
    },
    "slow-no-fade": {
        "label": "Slow No Fade",
        "just_buy_pre_wait_ms": 5000,
        "just_buy_interval_ms": 50,
        "just_buy_max_requests": 400,
        "just_buy_fade_interval_ms": None,
        "just_buy_fade_timeout": None,
    },
    "slow-fade": {
        "label": "Slow Fade",
        "just_buy_pre_wait_ms": 5000,
        "just_buy_interval_ms": 50,
        "just_buy_max_requests": 400,
        "just_buy_fade_interval_ms": 50,
        "just_buy_fade_timeout": 60,
    },
}

JUST_BUY_PRESET_OPTIONS = [(spec["label"], key) for key, spec in JUST_BUY_PRESETS.items()]

YES_NO_DEFAULTS = {
    "sell": False,
    "skip_first": False,
    "skip_second_last": False,
    "no_ladder": False,
    "double_buy": False,
    "just_buy": False,
    "multi_queue": False,
    "execute": False,
    "success": False,
}

QUICK_FIELD_SPECS = {
    "queue_id": {"label": "Queue", "presets": ["1", "2", "3", "4", "5", "9"], "type": "integer", "allow_none": False},
    "time": {"label": "Time", "presets": ["10:55", "11:00:00", "11:00:10"], "type": "text", "allow_none": True},
    "price": {"label": "Price", "presets": ["10", "100", "500", "800", "1000"], "type": "number", "allow_none": False},
    "quantity": {"label": "Quantity", "presets": ["509", "609", "709", "809" ,"1009"], "type": "integer", "allow_none": False},
    "base_quantity": {"label": "Base Qty", "presets": ["10", "20", "50", "100"], "type": "integer", "allow_none": False},
    "limit": {"label": "Limit", "presets": ["10", "100", "500", "800", "1000"], "type": "number", "allow_none": True},
    "double_buy_quantity": {"label": "Dbl Buy Qty", "presets": ["10", "20", "50", "100"], "type": "integer", "allow_none": True},
    "just_buy_interval_ms": {"label": "JB Interval (ms)", "presets": ["10", "20", "40", "50"], "type": "integer", "allow_none": False},
    "just_buy_timeout": {"label": "JB Timeout", "presets": ["3", "5", "10", "20"], "type": "integer", "allow_none": False},
    "just_buy_pre_wait_ms": {"label": "JB Pre Wait (ms)", "presets": ["1000", "2000", "5000", "10000"], "type": "integer", "allow_none": False},
    "just_buy_max_requests": {"label": "JB Max Requests", "presets": ["200", "400", "600"], "type": "integer", "allow_none": True},
    "just_buy_fade_interval_ms": {"label": "JB Fade Int (ms)", "presets": ["40", "50", "100"], "type": "integer", "allow_none": True},
    "just_buy_fade_timeout": {"label": "JB Fade Timeout", "presets": ["30", "60", "100", "120"], "type": "integer", "allow_none": True},
    "sell_quantity": {"label": "Sell Qty", "presets": ["10", "20", "50", "100"], "type": "integer", "allow_none": True},
    "sell_pre_wait_ms": {"label": "Sell Pre Wait (ms)", "presets": ["1000", "2000", "5000", "10000"], "type": "integer", "allow_none": False},
}

QUICK_FIELD_DEFAULTS = {
    "queue_id": "1",
    "time": "10:30",
    "price": "500",
    "quantity": "10",
    "base_quantity": "10",
    "limit": "",
    "double_buy_quantity": "",
    "just_buy_interval_ms": "20",
    "just_buy_timeout": "5",
    "just_buy_pre_wait_ms": "2000",
    "just_buy_max_requests": "400",
    "just_buy_fade_interval_ms": "50",
    "just_buy_fade_timeout": "60",
    "sell_quantity": "",
    "sell_pre_wait_ms": "5000",
}

TEXT_FIELD_DEFAULTS = {
    "seller_config": "",
    "buyer_config": "",
}


class OrderEditorScreen(Screen[tuple[str, dict] | None]):
    """Full-screen keyboard-first editor for all OrderStore-supported fields."""

    BINDINGS = [
        ("up", "focus_previous_control", "Prev"),
        ("down", "focus_next_control", "Next"),
        ("ctrl+1", "show_main", "Main"),
        ("ctrl+2", "show_buy", "Buy"),
        ("ctrl+3", "show_sell", "Sell"),
        ("ctrl+s", "submit", "Save"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, order_payload: dict) -> None:
        super().__init__()
        self.editor_title = title
        self.order_payload = order_payload

    def action_focus_next_control(self) -> None:
        self.focus_next("Button, Input, Select, Checkbox")

    def action_focus_previous_control(self) -> None:
        self.focus_previous("Button, Input, Select, Checkbox")

    def action_show_main(self) -> None:
        self.query_one(TabbedContent).active = "tab-main"

    def action_show_buy(self) -> None:
        self.query_one(TabbedContent).active = "tab-buy"

    def action_show_sell(self) -> None:
        self.query_one(TabbedContent).active = "tab-sell"

    def action_cancel(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" ORDERS ▸ {self.editor_title.upper()} ", classes="screen-title")
        with TabbedContent(initial="tab-main", id="order-tabs"):
            with TabPane("Main", id="tab-main"):
                with VerticalScroll(id="order-main-scroll"):
                    with Vertical(id="order-editor-form"):
                        yield Static(" STATUS", classes="form-section")
                        yield from self._compose_flag_row(
                            (
                                ("execute", "Execute"),
                                ("success", "Success"),
                            )
                        )

                        yield Static(" IDENTITY", classes="form-section")
                        yield from self._compose_input_row("Order ID", "order-id", str(self.order_payload.get("id", "")))
                        yield from self._compose_input_row("Ticker", "order-ticker", str(self.order_payload.get("ticker", "")))
                        with Horizontal(classes="form-row"):
                            yield Label("Mode", classes="form-label")
                            yield Select(
                                MODE_OPTIONS,
                                allow_blank=False,
                                value=str(self.order_payload.get("mode", "normal")),
                                id="order-mode",
                            )

                        yield Static(" CORE FIELDS", classes="form-section")
                        yield from self._compose_field("queue_id")
                        with Horizontal(classes="form-row"):
                            yield Label("Time", classes="form-label")
                            time_value = self.order_payload.get("time") or ""
                            time_select = Select(
                                TIME_OPTIONS,
                                allow_blank=True,
                                prompt="—",
                                id="order-input-time",
                            )
                            if time_value in {t[0] for t in TIME_OPTIONS}:
                                time_select.value = time_value
                            yield time_select
                        yield from self._compose_field("price")
                        yield from self._compose_field("limit")
                        yield from self._compose_field("quantity")
                        yield from self._compose_field("base_quantity")
                        with Horizontal(classes="form-row"):
                            yield Label("Est. (×1.1)", classes="form-label")
                            yield Static("—", id="order-cost-estimate", classes="form-calc")

            with TabPane("Buy", id="tab-buy"):
                with VerticalScroll(id="order-buy-scroll"):
                    with Vertical(id="order-buy-pane"):
                        yield Static(" BUY FLAGS", classes="form-section")
                        yield from self._compose_flag_row(
                            (
                                ("skip_first", "Skip First"),
                                ("skip_second_last", "Skip 2nd Last"),
                                ("no_ladder", "No Ladder"),
                            )
                        )
                        yield from self._compose_flag_row(
                            (
                                ("double_buy", "Double Buy"),
                                ("just_buy", "Just Buy"),
                                ("multi_queue", "Multi Queue"),
                            )
                        )
                        yield Static(" BUY LOGIC", classes="form-section")
                        yield from self._compose_field("double_buy_quantity")
                        yield Static(" JUST BUY SETTINGS", classes="form-section")
                        with Horizontal(classes="form-row"):
                            yield Label("Preset", classes="form-label")
                            yield Select(
                                JUST_BUY_PRESET_OPTIONS,
                                allow_blank=True,
                                prompt="— choose —",
                                id="order-just_buy-preset",
                            )
                        yield from self._compose_field("just_buy_interval_ms")
                        yield from self._compose_field("just_buy_timeout")
                        yield from self._compose_field("just_buy_pre_wait_ms")
                        yield from self._compose_field("just_buy_max_requests")
                        yield from self._compose_field("just_buy_fade_interval_ms")
                        yield from self._compose_field("just_buy_fade_timeout")

            with TabPane("Sell", id="tab-sell"):
                with VerticalScroll(id="order-sell-scroll"):
                    with Vertical(id="order-sell-pane"):
                        yield Static(" SELL FLAGS", classes="form-section")
                        yield from self._compose_flag_row((("sell", "Sell"),))
                        yield Static(" SELL / BUY TRIGGER", classes="form-section")
                        yield from self._compose_input_row(
                            "Seller Config",
                            "order-seller_config",
                            str(self.order_payload.get("seller_config", TEXT_FIELD_DEFAULTS["seller_config"])),
                        )
                        yield from self._compose_input_row(
                            "Buyer Config",
                            "order-buyer_config",
                            str(self.order_payload.get("buyer_config", TEXT_FIELD_DEFAULTS["buyer_config"])),
                        )
                        yield from self._compose_field("sell_quantity")
                        yield from self._compose_field("sell_pre_wait_ms")

        yield Static("", id="order-editor-status")
        yield ClockWidget(classes="panel-clock")
        with Horizontal(id="order-editor-actions"):
            yield Button("[Ctrl+S] Save", id="save", classes="action-button")
            yield Button("[Ctrl+1] Main", id="goto-main", classes="action-button")
            yield Button("[Ctrl+2] Buy", id="goto-buy", classes="action-button")
            yield Button("[Ctrl+3] Sell", id="goto-sell", classes="action-button")
            yield Button("[Esc] Cancel", id="cancel", classes="action-button")
        yield Footer()

    def _compose_input_row(self, label: str, input_id: str, value: str):
        with Horizontal(classes="form-row"):
            yield Label(label, classes="form-label")
            yield Input(value, id=input_id, classes="form-input")

    def _compose_field(self, field_name: str):
        spec = QUICK_FIELD_SPECS[field_name]
        raw_value = self.order_payload.get(field_name, QUICK_FIELD_DEFAULTS[field_name])
        value = "" if raw_value is None else str(raw_value)
        with Horizontal(classes="form-row"):
            yield Label(spec["label"], classes="form-label")
            yield Input(
                value,
                placeholder=" / ".join(spec["presets"]),
                id=f"order-input-{field_name}",
                type=spec["type"],
                classes="form-input",
            )

    def _compose_flag_row(self, row_group: tuple[tuple[str, str], ...]):
        with Horizontal(classes="flags-row"):
            for flag_name, flag_label in row_group:
                yield Checkbox(
                    flag_label,
                    value=bool(self.order_payload.get(flag_name, YES_NO_DEFAULTS[flag_name])),
                    id=f"order-{flag_name}",
                    classes="flag-cell",
                )

    def on_mount(self) -> None:
        self._apply_dependency_state()
        for checkbox in self.query(Checkbox):
            checkbox.set_class(bool(checkbox.value), "-on")
        self._update_cost_estimate()
        self.query_one("#order-id", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "goto-main":
            self.action_show_main()
            return
        if event.button.id == "goto-buy":
            self.action_show_buy()
            return
        if event.button.id == "goto-sell":
            self.action_show_sell()
            return
        self.action_submit()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "order-mode":
            self._apply_dependency_state()
        elif event.select.id == "order-just_buy-preset":
            self._apply_just_buy_preset(event.value)

    def _apply_just_buy_preset(self, preset_key) -> None:
        if not isinstance(preset_key, str) or preset_key not in JUST_BUY_PRESETS:
            return
        preset = JUST_BUY_PRESETS[preset_key]
        for field in (
            "just_buy_pre_wait_ms",
            "just_buy_interval_ms",
            "just_buy_max_requests",
            "just_buy_fade_interval_ms",
            "just_buy_fade_timeout",
        ):
            widget = self.query_one(f"#order-input-{field}", Input)
            if widget.disabled:
                continue
            raw = preset[field]
            widget.value = "" if raw is None else str(raw)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.checkbox.set_class(bool(event.checkbox.value), "-on")
        self._apply_dependency_state()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"order-input-price", "order-input-limit", "order-input-quantity"}:
            self._update_cost_estimate()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.focus_next("Button, Input, Select, Checkbox")

    def _update_cost_estimate(self) -> None:
        try:
            estimate = self.query_one("#order-cost-estimate", Static)
        except Exception:
            return

        def _num(input_id: str) -> float | None:
            try:
                widget = self.query_one(f"#{input_id}", Input)
            except Exception:
                return None
            if widget.disabled:
                return None
            raw = widget.value.strip()
            if not raw:
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        qty = _num("order-input-quantity")
        limit = _num("order-input-limit")
        price = _num("order-input-price")
        base = limit if limit is not None else price
        if qty is None or base is None:
            estimate.update("[#6b6b6b]—[/]")
            return
        total = qty * base * 1.1
        source = "limit" if limit is not None else "price"
        estimate.update(f"[bold #3ddc84]{total:,.2f}[/] [#6b6b6b]({source})[/]")

    def _set_checkbox_state(self, field_name: str, *, disabled: bool, value: bool | None = None) -> None:
        checkbox = self.query_one(f"#order-{field_name}", Checkbox)
        checkbox.disabled = disabled
        if value is not None:
            checkbox.value = value

    def _set_input_group_state(self, field_name: str, *, enabled: bool) -> None:
        input_widget = self.query_one(f"#order-input-{field_name}", Input)
        input_widget.disabled = not enabled
        if not enabled:
            spec = QUICK_FIELD_SPECS[field_name]
            input_widget.value = "" if spec["allow_none"] else QUICK_FIELD_DEFAULTS[field_name]

    def _set_text_input_state(self, field_name: str, *, enabled: bool) -> None:
        input_widget = self.query_one(f"#order-{field_name}", Input)
        input_widget.disabled = not enabled
        if not enabled:
            input_widget.value = ""

    def _apply_dependency_state(self) -> None:
        mode = str(self.query_one("#order-mode", Select).value)
        no_ladder = self.query_one("#order-no_ladder", Checkbox).value
        double_buy = self.query_one("#order-double_buy", Checkbox).value
        just_buy_enabled = no_ladder

        self._set_checkbox_state("just_buy", disabled=not just_buy_enabled, value=False if not just_buy_enabled else None)
        just_buy = self.query_one("#order-just_buy", Checkbox).value

        multi_queue_enabled = no_ladder and mode == "ipo-trigger"
        self._set_checkbox_state("multi_queue", disabled=not multi_queue_enabled, value=False if not multi_queue_enabled else None)

        self._set_input_group_state("limit", enabled=mode in {"ipo", "ipo-trigger", "ipo-trigger-low", "trigger-sell", "ipo-sell-buy-trigger"})
        self._set_input_group_state("double_buy_quantity", enabled=double_buy)

        just_buy_fields = (
            "just_buy_interval_ms",
            "just_buy_timeout",
            "just_buy_pre_wait_ms",
            "just_buy_max_requests",
            "just_buy_fade_interval_ms",
            "just_buy_fade_timeout",
        )
        for field_name in just_buy_fields:
            self._set_input_group_state(field_name, enabled=just_buy)

        sell_buy_trigger = mode == "ipo-sell-buy-trigger"
        self._set_text_input_state("seller_config", enabled=sell_buy_trigger)
        self._set_text_input_state("buyer_config", enabled=sell_buy_trigger)
        self._set_input_group_state("sell_quantity", enabled=sell_buy_trigger)
        self._set_input_group_state("sell_pre_wait_ms", enabled=sell_buy_trigger)

    def _read_required_input(self, input_id: str, label: str) -> str:
        value = self.query_one(f"#{input_id}", Input).value.strip()
        if not value:
            raise ValueError(f"{label} is required")
        return value

    def _read_optional_input(self, input_id: str) -> str | None:
        value = self.query_one(f"#{input_id}", Input).value.strip()
        return value or None

    def _read_quick_value(self, field_name: str):
        if field_name == "time":
            select = self.query_one("#order-input-time", Select)
            value = select.value
            if isinstance(value, str) and value:
                return value
            return None
        input_widget = self.query_one(f"#order-input-{field_name}", Input)
        if input_widget.disabled:
            return None
        raw_value = input_widget.value.strip()
        spec = QUICK_FIELD_SPECS[field_name]
        if raw_value == "":
            if spec["allow_none"]:
                return None
            raise ValueError(f"{spec['label']} is required")
        if spec["type"] == "integer":
            return int(raw_value)
        if spec["type"] == "number":
            return float(raw_value)
        return raw_value

    def action_submit(self) -> None:
        try:
            payload = {
                "id": self._read_required_input("order-id", "Order ID"),
                "ticker": self._read_required_input("order-ticker", "Ticker").upper(),
                "mode": str(self.query_one("#order-mode", Select).value),
                "queue_id": self._read_quick_value("queue_id"),
                "time": self._read_quick_value("time"),
                "price": self._read_quick_value("price"),
                "quantity": self._read_quick_value("quantity"),
                "base_quantity": self._read_quick_value("base_quantity"),
                "limit": self._read_quick_value("limit"),
                "sell": self.query_one("#order-sell", Checkbox).value,
                "skip_first": self.query_one("#order-skip_first", Checkbox).value,
                "skip_second_last": self.query_one("#order-skip_second_last", Checkbox).value,
                "no_ladder": self.query_one("#order-no_ladder", Checkbox).value,
                "double_buy": self.query_one("#order-double_buy", Checkbox).value,
                "double_buy_quantity": self._read_quick_value("double_buy_quantity"),
                "just_buy": self.query_one("#order-just_buy", Checkbox).value,
                "just_buy_interval_ms": self._read_quick_value("just_buy_interval_ms"),
                "just_buy_timeout": self._read_quick_value("just_buy_timeout"),
                "just_buy_pre_wait_ms": self._read_quick_value("just_buy_pre_wait_ms"),
                "just_buy_max_requests": self._read_quick_value("just_buy_max_requests"),
                "just_buy_fade_interval_ms": self._read_quick_value("just_buy_fade_interval_ms"),
                "just_buy_fade_timeout": self._read_quick_value("just_buy_fade_timeout"),
                "multi_queue": self.query_one("#order-multi_queue", Checkbox).value,
                "seller_config": self._read_optional_input("order-seller_config"),
                "buyer_config": self._read_optional_input("order-buyer_config"),
                "sell_quantity": self._read_quick_value("sell_quantity"),
                "sell_pre_wait_ms": self._read_quick_value("sell_pre_wait_ms"),
                "execute": self.query_one("#order-execute", Checkbox).value,
                "success": self.query_one("#order-success", Checkbox).value,
            }
        except ValueError as exc:
            self.query_one("#order-editor-status", Static).update(str(exc))
            return
        self.dismiss((payload["id"], payload))


class ConfirmDeleteScreen(ModalScreen[bool]):
    BINDINGS = [
        ("y", "confirm_remove", "Remove"),
        ("n", "dismiss(False)", "Cancel"),
        ("escape", "dismiss(False)", "Cancel"),
    ]

    def __init__(self, order_id: str) -> None:
        super().__init__()
        self.order_id = order_id

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-shell"):
            yield Static(f" CONFIRM ▸ REMOVE ORDER ▸ {self.order_id} ", classes="screen-title")
            with Horizontal():
                yield Button("[Y] Remove", id="confirm", classes="action-button")
                yield Button("[N] Cancel", id="cancel", classes="action-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def on_mount(self) -> None:
        self.query_one("#confirm", Button).focus()

    def action_confirm_remove(self) -> None:
        self.dismiss(True)


class OrdersScreen(Screen[None]):
    BINDINGS = [
        ("a", "add_order", "Add"),
        ("e", "edit_order", "Edit"),
        ("d", "delete_order", "Delete"),
        ("t", "toggle_execute", "Toggle Execute"),
        ("r", "refresh_prices", "Refresh Prices"),
        ("u", "refresh_store", "Reload Store"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(
        self,
        service: OrderStoreService | None = None,
        price_refresh_service: OrderPriceRefreshService | None = None,
    ) -> None:
        super().__init__()
        self.service = service or OrderStoreService()
        self.price_refresh_service = price_refresh_service or OrderPriceRefreshService()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" CONFIG ▸ ORDERS ▸ STORE EDITOR ", classes="screen-title")
        table = DataTable(
            id="orders-table",
            zebra_stripes=True,
            cursor_foreground_priority="renderable",
            cursor_background_priority="css",
        )
        table.cursor_type = "row"
        yield table
        yield Static("", id="orders-status")
        yield ClockWidget(classes="panel-clock")
        with Horizontal(id="orders-actions"):
            yield Button("[A] Add", id="add", classes="action-button")
            yield Button("[E] Edit", id="edit", classes="action-button")
            yield Button("[D] Remove", id="remove", classes="action-button")
            yield Button("[T] Toggle Execute", id="toggle-execute", classes="action-button")
            yield Button("[R] Refresh Prices", id="refresh-prices", classes="action-button")
            yield Button("[U] Reload Store", id="refresh-store", classes="action-button")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#orders-table", DataTable)
        table.add_columns(
            " TICKER",
            "  MODE",
            " Q",
            " EXEC",
            " MQ",
            " NL",
            " JB",
            "   TIME",
            "    PRICE",
            "    LIMIT",
            "     QTY",
            "       COST",
            "     CUM",
        )
        self.reload_table()
        table.focus()

    def reload_table(self) -> None:
        table = self.query_one("#orders-table", DataTable)
        table.clear()
        for row in self.service.list_rows():
            armed = bool(row.execute)
            mq = bool(row.multi_queue)
            jb = bool(row.just_buy)
            nl = bool(row.no_ladder)

            ticker_cell = f"[bold #e8e8e8]{row.ticker}[/]"
            mode_cell = f"[#ffd166]{row.mode}[/]"
            queue_cell = f"[#e8e8e8]{str(row.queue_id):>2}[/]"

            exec_cell = f"[bold #3ddc84]  ●[/]" if armed else f"[#6b6b6b]  ○[/]"
            mq_cell = f"[#ffd166] ●[/]" if mq else f"[#6b6b6b] ○[/]"
            jb_cell = f"[#ffd166] ●[/]" if jb else f"[#6b6b6b] ○[/]"
            nl_cell = f"[#ffd166] ●[/]" if nl else f"[#6b6b6b] ○[/]"
            time_cell = f"[#6b6b6b]{row.time or '-':<8}[/]"
            price_cell = f"[bold #e8e8e8]{row.price:>10,.2f}[/]"
            limit_text = f"{row.limit:>10,.2f}" if row.limit is not None else "-".rjust(10)
            limit_cell = f"[#ffd166]{limit_text}[/]" if row.limit is not None else f"[#6b6b6b]{limit_text}[/]"
            qty_cell = f"[#e8e8e8]{row.quantity:>8,}[/]"

            cost = int(row.total_cost)
            cum = int(row.cumulative_cost)
            cost_cell = f"[#e8e8e8]{cost:>12,}[/]"
            cum_cell = f"[#6b6b6b]{cum:>12,}[/]"

            table.add_row(
                ticker_cell,
                mode_cell,
                queue_cell,
                exec_cell,
                mq_cell,
                nl_cell,
                jb_cell,
                time_cell,
                price_cell,
                limit_cell,
                qty_cell,
                cost_cell,
                cum_cell,
                key=row.id,
            )

    def _selected_order_id(self) -> str | None:
        table = self.query_one("#orders-table", DataTable)
        if table.row_count == 0 or table.cursor_row < 0:
            return None
        row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
        return None if row_key is None else str(row_key.value)

    def _set_status(self, message: str) -> None:
        self.query_one("#orders-status", Static).update(message)

    def action_add_order(self) -> None:
        self.app.push_screen(
            OrderEditorScreen("Add Order", ORDER_TEMPLATE),
            self._handle_add_result,
        )

    def action_edit_order(self) -> None:
        order_id = self._selected_order_id()
        if not order_id:
            self._set_status("Select an order first.")
            return
        payload = self.service.get_order(order_id)
        if payload is None:
            self._set_status(f"Order '{order_id}' no longer exists.")
            return
        self.app.push_screen(
            OrderEditorScreen(f"Edit Order: {order_id}", payload),
            lambda result: self._handle_edit_result(order_id, result),
        )

    def action_delete_order(self) -> None:
        order_id = self._selected_order_id()
        if not order_id:
            self._set_status("Select an order first.")
            return
        self.app.push_screen(
            ConfirmDeleteScreen(order_id),
            lambda confirmed: self._handle_delete_result(order_id, confirmed),
        )

    def action_toggle_execute(self) -> None:
        order_id = self._selected_order_id()
        if not order_id:
            self._set_status("Select an order first.")
            return
        payload = self.service.get_order(order_id)
        if payload is None:
            self._set_status(f"Order '{order_id}' no longer exists.")
            return
        new_execute = not bool(payload.get("execute", False))
        update_payload: dict = {"execute": new_execute}
        if new_execute:
            update_payload["success"] = False
        try:
            self.service.update_order(order_id, update_payload)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self.reload_table()
        state = "ON" if new_execute else "OFF"
        suffix = " (success reset)" if new_execute else ""
        self._set_status(f"Execute {state} for '{order_id}'{suffix}.")

    def action_refresh_store(self) -> None:
        self.service.refresh_store()
        self.reload_table()
        self._set_status("Reloaded order store from disk.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            self.action_add_order()
        elif event.button.id == "edit":
            self.action_edit_order()
        elif event.button.id == "remove":
            self.action_delete_order()
        elif event.button.id == "toggle-execute":
            self.action_toggle_execute()
        elif event.button.id == "refresh-prices":
            self.action_refresh_prices()
        elif event.button.id == "refresh-store":
            self.action_refresh_store()

    @work(thread=True)
    def action_refresh_prices(self) -> None:
        self.app.call_from_thread(self._set_status, "Refreshing prices for all orders...")
        try:
            result = self.price_refresh_service.refresh_all()
        except ValueError as exc:
            self.app.call_from_thread(self._set_status, str(exc))
            return
        self.app.call_from_thread(self._handle_refresh_prices_result, result)

    def _handle_refresh_prices_result(self, result) -> None:
        self.service.refresh_store()
        self.reload_table()
        if result.message:
            self._set_status(result.message)
            return
        self._set_status(
            "Prices refreshed"
            f" | updated={result.updated_count}"
            f" skipped={result.skipped_count}"
            f" failed={result.failed_count}"
        )

    def _handle_add_result(self, result: tuple[str, dict] | None) -> None:
        if result is None:
            return
        _order_id, payload = result
        try:
            self.service.add_order(payload)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self.reload_table()
        self._set_status(f"Added order '{payload['id']}'.")

    def _handle_edit_result(
        self,
        existing_order_id: str,
        result: tuple[str, dict] | None,
    ) -> None:
        if result is None:
            return
        _order_id, payload = result
        try:
            updated = self.service.update_order(existing_order_id, payload)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self.reload_table()
        self._set_status(f"Updated order '{updated['id']}'.")

    def _handle_delete_result(self, order_id: str, confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            self.service.remove_order(order_id)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self.reload_table()
        self._set_status(f"Removed order '{order_id}'.")
