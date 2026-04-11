"""Main menu screen."""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, Button


class MainMenuScreen(Screen[None]):
    BINDINGS = [
        ("up", "focus_previous_control", "Previous"),
        ("down", "focus_next_control", "Next"),
        ("p", "open_portfolio", "Portfolio"),
        ("c", "open_config", "Config"),
        ("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" TMS ▸ MAIN MENU ", id="title")
        yield Button("[P] Portfolio", id="portfolio", classes="menu-button")
        yield Button("[C] Config", id="config", classes="menu-button")
        yield Button("[Q] Quit", id="quit", classes="menu-button")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "portfolio":
            self.action_open_portfolio()
        elif event.button.id == "config":
            self.action_open_config()
        elif event.button.id == "quit":
            self.app.exit()

    def on_mount(self) -> None:
        self.query_one("#portfolio", Button).focus()

    def action_open_portfolio(self) -> None:
        self.app.push_screen("portfolio")

    def action_open_config(self) -> None:
        self.app.push_screen("config")

    def action_focus_next_control(self) -> None:
        self.focus_next(Button)

    def action_focus_previous_control(self) -> None:
        self.focus_previous(Button)
