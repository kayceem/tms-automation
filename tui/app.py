"""Separate Textual entrypoint for TMS Automation."""

from __future__ import annotations

try:
    from textual.app import App
except ImportError as exc:  # pragma: no cover - dependency is optional until installed
    App = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from utils.logger import attach_handlers, detach_console_handlers


CSS = """
/*
 * TMS Automation :: Quant Terminal Theme
 *
 * Palette (Bloomberg-inspired):
 *   bg        #000000  pure black background
 *   panel     #0a0a0a  slightly raised surface
 *   amber     #ff9e1b  primary accent (titles, focus, brand)
 *   amber-dim #7a4a00  idle borders
 *   cyan      #5fd7ff  field labels
 *   white     #e8e8e8  primary data
 *   muted     #6b6b6b  secondary text
 *   green     #00d26a  success / buy
 *   red       #ff4757  error / sell
 *   yellow    #ffd166  warnings / status
 */

Screen {
    align: left top;
    padding: 0 1;
    background: #000000;
    color: #e8e8e8;
}

VerticalScroll {
    width: 100%;
    height: 1fr;
    margin: 0;
    scrollbar-background: #000000;
    scrollbar-color: #7a4a00;
    scrollbar-color-hover: #ff9e1b;
    scrollbar-color-active: #ff9e1b;
    scrollbar-size-vertical: 1;
}

#user-config-layout,
#order-editor-layout {
    width: 100%;
    height: 1fr;
    layout: vertical;
}

#confirm-shell {
    width: 90%;
    height: 90%;
    max-width: 120;
    border: heavy #ff9e1b;
    padding: 1 2;
    background: #0a0a0a;
}

#defaults-scroll,
#order-editor-scroll {
    width: 100%;
    height: 1fr;
    scrollbar-background: #000000;
    scrollbar-color: #7a4a00;
    scrollbar-color-hover: #ff9e1b;
    scrollbar-size-vertical: 1;
    overflow-y: auto;
}

#order-editor-form,
#defaults-form {
    width: 100%;
    height: auto;
}

#title, .screen-title {
    width: 100%;
    content-align: left middle;
    margin: 0 0 1 0;
    padding: 0 1;
    text-style: bold;
    color: #000000;
    background: #ff9e1b;
}

Button {
    width: auto;
    min-width: 12;
    height: 1;
    margin: 0 1 0 0;
    background: #000000;
    color: #ff9e1b;
    border: none;
    text-style: bold;
    padding: 0 1;
}

Button:hover {
    background: #1a1000;
    color: #ffd166;
}

Button.-active,
Button:focus {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

Button:disabled {
    color: #4a4a4a;
    background: #000000;
}

DataTable {
    width: 100%;
    height: 1fr;
    margin: 0;
    background: #000000;
    color: #e8e8e8;
    border: solid #7a4a00;
    scrollbar-background: #000000;
    scrollbar-color: #7a4a00;
    scrollbar-size-vertical: 1;
}

DataTable:focus {
    border: solid #ff9e1b;
}

DataTable > .datatable--header {
    background: #1a1000;
    color: #ff9e1b;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

DataTable > .datatable--hover {
    background: #1a1000;
}

DataTable > .datatable--odd-row {
    background: #050505;
}

TextArea {
    width: 100%;
    height: 1fr;
    margin: 0 0 1 0;
    background: #0a0a0a;
    color: #e8e8e8;
    border: solid #7a4a00;
}

Input, Select {
    width: 100%;
    margin: 0 0 1 0;
    background: #0a0a0a;
    color: #e8e8e8;
    border: solid #7a4a00;
}

Input:focus, Select:focus {
    border: solid #ff9e1b;
    background: #0a0a0a;
    color: #ffffff;
}

Input.-invalid {
    border: solid #ff4757;
}

Checkbox {
    margin: 0;
    padding: 0 1;
    background: #000000;
    color: #5fd7ff;
    border: none;
}

Checkbox:focus {
    background: #1a1000;
    color: #ff9e1b;
    text-style: bold;
}

.field-pair {
    width: 100%;
    height: auto;
}

/* Dense horizontal form rows: [ label ][ input ] on one line.
 * Row height is auto so focused inputs can expand without shifting labels
 * off the visible line. */
.form-row {
    width: 100%;
    height: auto;
    margin: 0;
    align: left middle;
}

.form-label {
    width: 22;
    height: 1;
    padding: 0 1 0 0;
    margin: 0;
    color: #5fd7ff;
    background: #000000;
    content-align: right middle;
    text-style: bold;
}

.form-input {
    width: 1fr;
    height: 1;
    margin: 0;
    padding: 0 1;
    border: none;
    background: #0a0a0a;
    color: #e8e8e8;
}

/* On focus, input grows to 3 rows with a solid amber frame so typed text
 * is clearly visible. The parent .form-row grows to match. */
.form-input:focus {
    height: 3;
    border: solid #ff9e1b;
    background: #1a1000;
    color: #ffffff;
}

.form-input:disabled {
    background: #050505;
    color: #4a4a4a;
}

.form-row Select {
    width: 1fr;
    margin: 0;
}

.form-col {
    width: 1fr;
    height: auto;
    padding: 0 1 0 0;
}

#order-editor-cols {
    width: 100%;
    height: auto;
    margin: 1 0 0 0;
}

.form-section {
    width: 100%;
    height: 1;
    margin: 1 0 0 0;
    padding: 0 1;
    color: #ff9e1b;
    background: #000000;
    text-style: bold;
}

.flags-row {
    width: 100%;
    height: 1;
    margin: 0;
    align: left middle;
}

.flag-cell {
    width: 1fr;
    height: 1;
    margin: 0;
    padding: 0 1;
    border: none;
    background: #000000;
    color: #5fd7ff;
}

.flag-cell:focus {
    background: #1a1000;
    color: #ff9e1b;
    text-style: bold;
}

.flag-cell:disabled {
    color: #3a3a3a;
}

.action-button {
    width: auto;
    min-width: 10;
    margin: 0 1 0 0;
}

.menu-button {
    width: 32;
    height: 1;
    margin: 0 0 1 0;
    content-align: left middle;
    background: #000000;
    color: #ff9e1b;
    border: none;
    padding: 0 1;
}

.menu-button:hover {
    background: #1a1000;
    color: #ffd166;
}

.menu-button:focus {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

#config-status, #orders-status, #order-book-status, #atrad-users-status, #order-editor-status {
    width: 100%;
    padding: 0 1;
    margin: 1 0 0 0;
    background: #0a0a0a;
    color: #ffd166;
}

#order-book-response {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 1 0 0 0;
    background: #0a0a0a;
    color: #5fd7ff;
}

Label {
    color: #5fd7ff;
    margin: 0;
    text-style: bold;
}

#defaults-form {
    width: 100%;
    margin: 1 0;
}

#order-editor-actions,
#user-config-actions {
    width: 100%;
    height: auto;
    align: left middle;
    padding: 1 0 0 0;
}

Header {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

Header > .header--title {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

Header > .header--sub_title {
    background: #ff9e1b;
    color: #000000;
}

Footer {
    background: #0a0a0a;
    color: #6b6b6b;
}

Footer > .footer--key {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

Footer > .footer--description {
    background: #0a0a0a;
    color: #e8e8e8;
}

Footer > .footer--highlight {
    background: #1a1000;
    color: #ff9e1b;
}

Footer > .footer--highlight-key {
    background: #ff9e1b;
    color: #000000;
    text-style: bold;
}

ModalScreen {
    align: center middle;
    background: #000000 70%;
}

/* TabbedContent :: quant terminal tabs */
TabbedContent {
    height: 1fr;
    background: #000000;
}

TabbedContent > Tabs {
    background: #000000;
}

Tab {
    padding: 0 2;
    color: #6b6b6b;
    background: #000000;
}

Tab:hover {
    color: #ffd166;
    background: #1a1000;
}

Tab.-active {
    color: #ff9e1b;
    background: #000000;
    text-style: bold;
}

Underline > .underline--bar {
    color: #ff9e1b;
    background: #000000;
}

TabPane {
    padding: 0 1;
    background: #000000;
}

#order-flags-pane {
    width: 100%;
    height: auto;
    padding: 1 0;
}
"""


if App is not None:
    from tui.screens.config_menu import ConfigMenuScreen, UserConfigScreen
    from tui.screens.main_menu import MainMenuScreen
    from tui.screens.orders import OrdersScreen
    from tui.screens.portfolio import ATRADUserSelectScreen, PortfolioScreen

    class TMSAutomationTUI(App[None]):
        CSS = CSS
        TITLE = "TMS AUTO"
        SUB_TITLE = "OPERATOR TERMINAL"
        SCREENS = {
            "main": MainMenuScreen,
            "config": ConfigMenuScreen,
            "user-config": UserConfigScreen,
            "orders": OrdersScreen,
            "portfolio": PortfolioScreen,
            "atrad-users": ATRADUserSelectScreen,
        }

        def __init__(self) -> None:
            super().__init__()
            self._detached_log_handlers = []

        def on_mount(self) -> None:
            self._detached_log_handlers = detach_console_handlers("main")
            self.push_screen("main")

        def on_exit(self) -> None:
            attach_handlers("main", self._detached_log_handlers)


def main() -> None:
    if App is None:
        raise SystemExit(
            "Textual is not installed. Run `uv sync` after adding dependencies, "
            "or install `textual` before launching the TUI."
        ) from _IMPORT_ERROR
    TMSAutomationTUI().run()
