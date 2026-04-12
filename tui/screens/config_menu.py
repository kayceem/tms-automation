"""Configuration menu screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from tui.services.config import ConfigActionsService


DEFAULT_FIELDS = (
    ("trigger_mode_poll_interval_ms", "Trigger poll (ms)"),
    ("multi_fetch_poll_interval_ms", "Multi-fetch poll (ms)"),
    ("trigger_mode_refresh_interval_seconds", "Refresh interval (s)"),
    ("trigger_sell_poll_interval_ms", "Sell poll (ms)"),
    ("trigger_mode_slow_poll_interval_ms", "Slow poll (ms)"),
    ("trigger_mode_requests_per_fetch_user", "Requests per user"),
)

DEFAULT_PRESETS = {
    "trigger_mode_poll_interval_ms": ["5", "10", "20"],
    "multi_fetch_poll_interval_ms": ["100", "150", "200", "250"],
    "trigger_mode_refresh_interval_seconds": ["30", "60"],
    "trigger_sell_poll_interval_ms": ["100", "150", "200", "250"],
    "trigger_mode_slow_poll_interval_ms": ["150", "250", "500"],
    "trigger_mode_requests_per_fetch_user": ["1", "2", "5", "10"],
}


class FocusableScreen(Screen[None]):
    BINDINGS = [
        ("up", "focus_previous_control", "Previous"),
        ("down", "focus_next_control", "Next"),
    ]

    def action_focus_next_control(self) -> None:
        self.focus_next("Button, Input, Select")

    def action_focus_previous_control(self) -> None:
        self.focus_previous("Button, Input, Select")


class ConfigMenuScreen(FocusableScreen):
    BINDINGS = FocusableScreen.BINDINGS + [
        ("u", "open_user_tools", "User"),
        ("o", "open_orders", "Orders"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" CONFIG ▸ MENU ", classes="screen-title")
        yield Button("[U] User Defaults", id="user", classes="menu-button")
        yield Button("[O] Orders", id="orders", classes="menu-button")
        yield Button("[Esc] Back", id="back", classes="menu-button")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "user":
            self.action_open_user_tools()
        elif event.button.id == "orders":
            self.action_open_orders()
        elif event.button.id == "back":
            self.app.pop_screen()

    def on_mount(self) -> None:
        self.query_one("#user", Button).focus()

    def action_open_user_tools(self) -> None:
        self.app.push_screen("user-config")

    def action_open_orders(self) -> None:
        self.app.push_screen("orders")


class UserConfigScreen(FocusableScreen):
    BINDINGS = FocusableScreen.BINDINGS + [
        ("r", "reset_jsession", "Reset Session"),
        ("ctrl+s", "save_defaults", "Save"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, service: ConfigActionsService | None = None) -> None:
        super().__init__()
        self.service = service or ConfigActionsService()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" CONFIG ▸ USER DEFAULTS ▸ TRIGGER SETTINGS ", classes="screen-title")
        with Vertical(id="user-config-layout"):
            with Horizontal(id="user-config-actions"):
                yield Button("[R] Reset JSESSIONID", id="reset", classes="action-button")
                yield Button("[Ctrl+S] Save", id="save", classes="action-button")
                yield Button("[Esc] Back", id="back", classes="action-button")
            with Vertical(id="defaults-form"):
                for field_name, label in DEFAULT_FIELDS:
                    with Horizontal(classes="form-row"):
                        yield Label(label, classes="form-label")
                        yield Input(
                            placeholder=" / ".join(DEFAULT_PRESETS[field_name]),
                            id=f"default-input-{field_name}",
                            type="integer",
                            classes="form-input",
                        )
        yield Static("", id="config-status")
        yield Footer()

    def on_mount(self) -> None:
        defaults = self.service.load_defaults()
        for field_name, _label in DEFAULT_FIELDS:
            value = defaults.get(field_name)
            if value is not None:
                self.query_one(f"#default-input-{field_name}", Input).value = str(value)
        self.query_one(f"#default-input-{DEFAULT_FIELDS[0][0]}", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "reset":
            self.action_reset_jsession()
            return
        if event.button.id == "save":
            self.action_save_defaults()

    def _set_status(self, message: str) -> None:
        self.query_one("#config-status", Static).update(message)

    def action_reset_jsession(self) -> None:
        results = self.service.reset_jsession_ids()
        if results:
            self._set_status(
                f"Reset JSESSIONID for {len(results)} ATRAD user file(s)."
            )
        else:
            self._set_status("No ATRAD user files found.")

    def action_save_defaults(self) -> None:
        try:
            payload = {
                field_name: self.query_one(f"#default-input-{field_name}", Input).value
                for field_name, _label in DEFAULT_FIELDS
            }
            path = self.service.save_defaults(payload)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Saved defaults to {path}")
