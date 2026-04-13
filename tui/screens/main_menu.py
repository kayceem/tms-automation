"""Main menu screen."""

from textual.app import ComposeResult
from textual.containers import Vertical
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
        with Vertical(classes="menu-shell"):
            yield Static(" TMS ▸ MAIN MENU ", id="title")
            yield Static("Operator shortcuts and entry points. Use [bold]Q[/] to quit.", classes="menu-subtitle")
            with Vertical(classes="menu-section"):
                with Vertical(classes="menu-list"):
                    yield Button(
                        "[bold #ff9e1b]P[/]  Portfolio  [#6b6b6b]ATRAD order book and account views[/]",
                        id="portfolio",
                        classes="menu-item",
                    )
                    yield Static("─" * 64, classes="menu-divider")
                    yield Button(
                        "[bold #ff9e1b]C[/]  Config     [#6b6b6b]Defaults, order store, and runtime settings[/]",
                        id="config",
                        classes="menu-item",
                    )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "portfolio":
            self.action_open_portfolio()
        elif event.button.id == "config":
            self.action_open_config()

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
