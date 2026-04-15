"""Separate Textual entrypoint for TMS Automation."""

from __future__ import annotations

import logging

try:
    from textual.app import App
except ImportError as exc:  # pragma: no cover - dependency is optional until installed
    App = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from utils.logger import setup_logger


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

.menu-shell {
    width: 100%;
    max-width: 84;
    padding: 0;
    align: left top;
}

.menu-subtitle {
    width: 100%;
    margin: 0 0 1 0;
    padding: 0 1;
    color: #6b6b6b;
}

.menu-section {
    width: 100%;
    margin: 0;
    border: tall #1a1000;
    background: #050505;
    padding: 0 1;
    align: left top;
}

.menu-list {
    width: 100%;
    height: auto;
    align: left top;
}

.menu-item {
    width: 100%;
    min-width: 0;
    height: auto;
    margin: 0;
    padding: 0 1;
    background: #050505;
    color: #e8e8e8;
    border: none;
    content-align: left middle;
    text-align: left;
}

.menu-item:hover {
    background: #1a1000;
    color: #ffd166;
}

.menu-item:focus,
.menu-item.-active {
    background: #ffffff 22%;
    color: #ffffff;
    text-style: bold;
}

.menu-item:disabled {
    color: #4a4a4a;
    background: #050505;
}

.menu-key {
    color: #ff9e1b;
    text-style: bold;
}

.menu-meta {
    color: #6b6b6b;
}

.menu-divider {
    width: 100%;
    height: 1;
    color: #1a1000;
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
#order-editor-layout,
#order-logs-layout {
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
    background: #ffffff 20%;
    color: #ffffff;
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

.form-row {
    width: 100%;
    height: 1;
    margin: 0;
    align: left middle;
}

.form-label {
    width: 18;
    height: 1;
    padding: 0 1 0 1;
    margin: 0;
    color: #8a8a8a;
    background: #000000;
    content-align: right middle;
    text-style: none;
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

.form-input:focus {
    border: none;
    background: #1a1000;
    color: #ffffff;
    text-style: bold;
}

.form-input:disabled {
    background: #050505;
    color: #3a3a3a;
}

.form-calc {
    width: 1fr;
    height: 1;
    padding: 0 1;
    background: #0a0a0a;
    color: #e8e8e8;
}

.form-row Select {
    width: 1fr;
    margin: 0;
    height: 1;
    border: none;
    background: #0a0a0a;
    color: #e8e8e8;
}

.form-row Select:focus {
    background: #1a1000;
    color: #ffffff;
    border: none;
}

.form-row Select SelectCurrent {
    width: 1fr;
    height: 1;
    border: none;
    background: #0a0a0a;
    color: #e8e8e8;
    padding: 0 1;
}

.form-row Select SelectCurrent:focus {
    background: #1a1000;
    color: #ffffff;
    border: none;
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
    background: #0a0a0a;
    text-style: bold;
}

.flags-row {
    width: 100%;
    height: 1;
    margin: 0 0 0 0;
    align: left middle;
    background: #000000;
}

.flag-cell {
    width: 1fr;
    height: 1;
    margin: 0;
    padding: 0 1;
    border: none;
    background: #000000;
    color: #6b6b6b;
}

.flag-cell.-on {
    color: #3ddc84;
    text-style: bold;
}

.flag-cell:focus {
    background: #1a1000;
    color: #ff9e1b;
    text-style: bold;
}

.flag-cell:disabled {
    color: #2a2a2a;
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

#config-status, #orders-status, #order-book-status, #completed-order-book-status, #watchlist-status, #atrad-users-status, #order-editor-status, #portfolio-status {
    background: #0a0a0a;
    color: #ffd166;
}

#order-book-total, #completed-order-book-total, #portfolio-total {
    background: #0a0a0a;
    color: #5fd7ff;
}

.response-scroll {
    width: 100%;
    height: 4;
    margin: 1 0 0 0;
    background: #0a0a0a;
    scrollbar-background: #000000;
    scrollbar-color: #7a4a00;
    scrollbar-color-hover: #ff9e1b;
    scrollbar-size-vertical: 1;
}

.response-text {
    width: 100%;
    height: auto;
    padding: 0 1;
    background: #0a0a0a;
    color: #5fd7ff;
}

#watchlist-table,
#order-book-table,
#completed-order-book-table,
#orders-table {
    border: round #7a4a00;
    padding: 0;
}

#watchlist-table:focus,
#order-book-table:focus,
#completed-order-book-table:focus,
#orders-table:focus {
    border: round #ff9e1b;
}

#watchlist-table > .datatable--header,
#order-book-table > .datatable--header,
#completed-order-book-table > .datatable--header,
#orders-table > .datatable--header {
    background: #0a0a0a;
    color: #ff9e1b;
    text-style: bold;
}

#watchlist-table > .datatable--odd-row,
#order-book-table > .datatable--odd-row,
#completed-order-book-table > .datatable--odd-row,
#orders-table > .datatable--odd-row {
    background: #050505;
}

#watchlist-table > .datatable--even-row,
#order-book-table > .datatable--even-row,
#completed-order-book-table > .datatable--even-row,
#orders-table > .datatable--even-row {
    background: #000000;
}

#market-tables {
    width: 100%;
    height: auto;
    align: center top;
    padding: 0;
}

#market-bids-table, #market-asks-table {
    width: 40;
    max-width: 50%;
    height: auto;
    max-height: 14;
    margin: 0 1;
    border: solid #7a4a00;
}

#market-bids-table:focus, #market-asks-table:focus {
    border: solid #ff9e1b;
}

.market-ltp {
    width: 100%;
    height: auto;
    padding: 1 2;
    margin: 0;
    background: #050505;
    color: #e8e8e8;
    border: none;
}

#market-ltp-scroll {
    width: 100%;
    height: 15;
    min-height: 15;
    margin: 1 0 0 0;
    background: #050505;
    border: tall #1a1000;
    scrollbar-background: #000000;
    scrollbar-color: #7a4a00;
    scrollbar-color-hover: #ff9e1b;
    scrollbar-size-vertical: 1;
}

#symbol-prompt-shell {
    width: 60;
    height: auto;
    max-height: 20;
    border: heavy #ff9e1b;
    padding: 1 2;
    background: #0a0a0a;
}

#symbol-suggestions {
    width: 100%;
    height: auto;
    max-height: 10;
    margin: 0 0 1 0;
    background: #050505;
    border: solid #7a4a00;
    color: #e8e8e8;
    scrollbar-background: #000000;
    scrollbar-color: #7a4a00;
    scrollbar-color-hover: #ff9e1b;
    scrollbar-size-vertical: 1;
}

#symbol-suggestions:focus {
    border: solid #ff9e1b;
}

#symbol-suggestions > .option-list--option-highlighted {
    background: #1a1000;
    color: #ffd166;
}

#symbol-suggestions > .option-list--option-hover {
    background: #1a1000;
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
#user-config-actions,
#orders-actions,
#portfolio-actions,
#order-logs-actions {
    width: 100%;
    height: auto;
    align: left middle;
    padding: 1 0 0 0;
    margin: 0 0 1 0;
}

#portfolio-actions-spacer {
    width: 1fr;
    height: 1;
    background: #000000;
}

#portfolio-actions #watchlist-selector {
    width: 24;
    height: 1;
    margin: 0;
    border: none;
    background: #000000;
    color: #ff9e1b;
}

#portfolio-actions #watchlist-selector:focus {
    background: #1a1000;
    color: #ffd166;
    border: none;
}

#portfolio-actions #watchlist-selector SelectCurrent {
    width: 24;
    height: 1;
    border: none;
    padding: 0 1;
    background: #000000;
    color: #ff9e1b;
}

#portfolio-actions #watchlist-selector SelectCurrent:focus {
    background: #1a1000;
    color: #ffd166;
    border: none;
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
    from tui.screens.order_logs import OrderLogsScreen
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
            "order-logs": OrderLogsScreen,
        }

        def __init__(self) -> None:
            super().__init__()
            self._original_log_handlers = []
            self._original_log_level = logging.INFO

        def on_mount(self) -> None:
            logger = logging.getLogger("main")
            self._original_log_handlers = list(logger.handlers)
            self._original_log_level = logger.level or logging.INFO
            logger.handlers.clear()
            setup_logger(
                name="main",
                log_file="tui.log",
                level=self._original_log_level,
                console_output=False,
                log_root="logs/tui",
            )
            self.push_screen("main")

        def on_exit(self) -> None:
            logger = logging.getLogger("main")
            logger.handlers.clear()
            logger.setLevel(self._original_log_level)
            logger.propagate = False
            for handler in self._original_log_handlers:
                logger.addHandler(handler)


def main() -> None:
    if App is None:
        raise SystemExit(
            "Textual is not installed. Run `uv sync` after adding dependencies, "
            "or install `textual` before launching the TUI."
        ) from _IMPORT_ERROR
    TMSAutomationTUI().run()
