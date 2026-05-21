import asyncio
import time
from pathlib import Path

import pytest


textual = pytest.importorskip("textual")

from textual.widgets import Checkbox, Input, TabbedContent

from tui.app import TMSAutomationTUI
from tui.screens.main_menu import MainMenuScreen
from tui.screens.config_menu import ConfigMenuScreen
from tui.screens.order_logs import OrderLogsScreen
from tui.screens.orders import ORDER_TEMPLATE, OrderEditorScreen
from tui.screens.portfolio import ATRADUserSelectScreen, MeroSharePortfolioScreen, MeroShareUserSelectScreen, OrderBookScreen, PortfolioScreen
from tui.screens.orders import OrdersScreen


def _binding_key(binding) -> str:
    return binding.key if hasattr(binding, "key") else binding[0]


def _binding_action(binding) -> str:
    return binding.action if hasattr(binding, "action") else binding[1]


def test_tui_main_screen_mounts():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(run())


def test_global_shortcut_ctrl_o_opens_config_orders():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+o")
            await pilot.pause()

            assert isinstance(app.screen, OrdersScreen)
            assert len(app.screen_stack) == 4
            assert isinstance(app.screen_stack[-3], MainMenuScreen)
            assert isinstance(app.screen_stack[-2], ConfigMenuScreen)
            assert isinstance(app.screen_stack[-1], OrdersScreen)

    asyncio.run(run())


def test_global_shortcut_ctrl_l_opens_order_logs():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+l")
            await pilot.pause()

            assert isinstance(app.screen, OrderLogsScreen)
            assert len(app.screen_stack) == 3
            assert isinstance(app.screen_stack[-2], MainMenuScreen)
            assert isinstance(app.screen_stack[-1], OrderLogsScreen)

    asyncio.run(run())


def test_global_shortcut_ctrl_a_opens_portfolio_atrad():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+a")
            await pilot.pause()

            assert isinstance(app.screen, ATRADUserSelectScreen)
            assert len(app.screen_stack) == 4
            assert isinstance(app.screen_stack[-3], MainMenuScreen)
            assert isinstance(app.screen_stack[-2], PortfolioScreen)
            assert isinstance(app.screen_stack[-1], ATRADUserSelectScreen)

    asyncio.run(run())


def test_global_shortcut_ctrl_w_opens_portfolio_meroshare():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("ctrl+w")
            await pilot.pause()

            assert isinstance(app.screen, MeroShareUserSelectScreen)
            assert len(app.screen_stack) == 4
            assert isinstance(app.screen_stack[-3], MainMenuScreen)
            assert isinstance(app.screen_stack[-2], PortfolioScreen)
            assert isinstance(app.screen_stack[-1], MeroShareUserSelectScreen)

    asyncio.run(run())


def test_order_editor_uses_main_buy_users_sell_tabs():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            screen = OrderEditorScreen("Add Order", ORDER_TEMPLATE)
            app.push_screen(screen)
            await pilot.pause()

            tabs = screen.query_one(TabbedContent)
            assert tabs.active == "tab-main"
            assert screen.query_one("#tab-main") is not None
            assert screen.query_one("#tab-buy") is not None
            assert screen.query_one("#tab-users") is not None
            assert screen.query_one("#tab-sell") is not None

            assert screen.query_one("#order-execute", Checkbox) is not None
            assert screen.query_one("#order-success", Checkbox) is not None
            assert screen.query_one("#order-sell", Checkbox) is not None
            assert screen.query_one("#order-user_id", Input) is not None

            assert screen.query_one("#order-just_buy", Checkbox).disabled is True
            assert screen.query_one("#order-multi_queue", Checkbox).disabled is True

    asyncio.run(run())


def test_order_editor_submits_user_id_field():
    class TestScreen(OrderEditorScreen):
        def __init__(self) -> None:
            super().__init__("Edit Order", {**ORDER_TEMPLATE, "user_id": "pool-main"})
            self.result = None

        def dismiss(self, result=None):
            self.result = result

    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            screen = TestScreen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#order-user_id", Input).value = "pool-main"
            screen.action_submit()

            assert screen.result is not None
            payload = screen.result[1]
            assert payload["user_id"] == "pool-main"

    asyncio.run(run())


def test_order_editor_digit_shortcut_sets_atrad_user_id():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            screen = OrderEditorScreen("Add Order", ORDER_TEMPLATE)
            app.push_screen(screen)
            await pilot.pause()

            user_input = screen.query_one("#order-user_id", Input)
            user_input.focus()
            await pilot.pause()

            await pilot.press("3")
            await pilot.pause()

            assert user_input.value == "atrad_user3"

    asyncio.run(run())


def test_order_book_auto_refresh_only_targets_active_panel():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    class FakeTimer:
        def __init__(self) -> None:
            self.resume_calls = 0
            self.pause_calls = 0
            self.reset_calls = 0

        def resume(self) -> None:
            self.resume_calls += 1

        def pause(self) -> None:
            self.pause_calls += 1

        def reset(self) -> None:
            self.reset_calls += 1

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    timer = FakeTimer()
    messages: list[tuple[str, str]] = []
    refresh_requests: list[str] = []

    screen._auto_refresh_timer = timer
    screen._active_panel = lambda: "tab-completed"  # type: ignore[method-assign]
    screen._update_refresh_button = lambda: None  # type: ignore[method-assign]
    screen._set_status = lambda message, panel="active": messages.append((message, panel))  # type: ignore[method-assign]
    screen._trigger_refresh = lambda *, source: refresh_requests.append(f"{source}:{screen._active_panel()}")  # type: ignore[method-assign]
    screen._is_market_hours = lambda: True  # type: ignore[method-assign]

    try:
        assert screen._auto_refresh_enabled is False
        assert any(_binding_key(binding) == "l" for binding in screen.BINDINGS)

        screen._handle_auto_refresh_tick()
        assert refresh_requests == []

        screen.action_toggle_auto_refresh()
        assert screen._auto_refresh_enabled is True
        assert timer.reset_calls == 1
        assert timer.resume_calls == 1
        assert messages[-1] == ("Auto-refresh enabled for active panel every 30s", "completed")

        screen._handle_auto_refresh_tick()
        assert refresh_requests == ["auto:tab-completed"]

        screen.action_toggle_auto_refresh()
        assert screen._auto_refresh_enabled is False
        assert timer.pause_calls == 1
        assert messages[-1] == ("Auto-refresh disabled for active panel every 30s", "completed")
    finally:
        pass


def test_order_book_top_tab_defaults_and_toggle_behavior():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    refresh_calls: list[str] = []
    statuses: list[tuple[str, str]] = []

    screen._active_panel = lambda: "tab-top"  # type: ignore[method-assign]
    screen.action_refresh_book = lambda: refresh_calls.append("refresh")  # type: ignore[method-assign]
    screen._set_status = lambda message, panel="active": statuses.append((message, panel))  # type: ignore[method-assign]

    assert screen._top_gainers_mode is True
    assert any(_binding_key(binding) == "ctrl+4" and _binding_action(binding) == "show_top_panel" for binding in screen.BINDINGS)
    assert any(_binding_key(binding) == "ctrl+5" and _binding_action(binding) == "show_market_panel" for binding in screen.BINDINGS)
    assert any(_binding_key(binding) == "ctrl+6" and _binding_action(binding) == "show_market_depth_panel" for binding in screen.BINDINGS)
    assert any(_binding_key(binding) == "ctrl+7" and _binding_action(binding) == "show_portfolio_panel" for binding in screen.BINDINGS)
    assert any(_binding_key(binding) == "ctrl+8" and _binding_action(binding) == "show_account_panel" for binding in screen.BINDINGS)
    assert screen._top_sort_mode == "chng_pct"

    screen.action_toggle_top_or_cycle_watchlist()
    assert screen._top_gainers_mode is False
    assert refresh_calls == ["refresh"]
    assert statuses[-1] == ("Top 10 mode: Losers", "top")


def test_order_book_t_binding_is_noop_outside_watchlists_and_top():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    calls: list[str] = []

    screen._active_panel = lambda: "tab-active"  # type: ignore[method-assign]
    screen.action_cycle_watchlist = lambda: calls.append("cycle")  # type: ignore[method-assign]
    screen.action_refresh_book = lambda: calls.append("refresh")  # type: ignore[method-assign]

    screen.action_toggle_top_or_cycle_watchlist()
    assert calls == []


def test_order_book_panel_switch_refreshes_every_time():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    class FakeTabs:
        def __init__(self) -> None:
            self.active = "tab-active"

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    tabs = FakeTabs()
    refresh_calls: list[str] = []
    focus_calls: list[str] = []
    action_updates: list[str] = []

    screen.query_one = lambda selector, _type=None: tabs if selector == "#portfolio-tabs" else None  # type: ignore[method-assign]
    screen._focus_current_panel = lambda: focus_calls.append(tabs.active)  # type: ignore[method-assign]
    screen._update_action_buttons = lambda: action_updates.append(tabs.active)  # type: ignore[method-assign]
    screen.action_refresh_book = lambda: refresh_calls.append(tabs.active)  # type: ignore[method-assign]

    screen._set_panel("tab-market")
    screen._loaded_panels.add("tab-market")
    screen._set_panel("tab-portfolio")
    screen._loaded_panels.add("tab-portfolio")
    screen._set_panel("tab-market")
    screen._set_panel("tab-portfolio")

    assert refresh_calls == ["tab-market", "tab-portfolio", "tab-market", "tab-portfolio"]
    assert focus_calls == ["tab-market", "tab-portfolio", "tab-market", "tab-portfolio"]
    assert action_updates == ["tab-market", "tab-portfolio", "tab-market", "tab-portfolio"]


def test_order_book_account_panel_focuses_scroll_container():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    class FakeTabs:
        def __init__(self) -> None:
            self.active = "tab-account"

    class FocusTarget:
        def __init__(self, name: str, calls: list[str]) -> None:
            self.name = name
            self.calls = calls

        def focus(self) -> None:
            self.calls.append(self.name)

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    focus_calls: list[str] = []
    tabs = FakeTabs()
    targets = {
        "#portfolio-tabs": tabs,
        "#account-summary-scroll": FocusTarget("account-scroll", focus_calls),
    }

    screen.query_one = lambda selector, _type=None: targets[selector]  # type: ignore[method-assign]

    screen._focus_current_panel()

    assert focus_calls == ["account-scroll"]


def test_order_book_market_depth_panel_focuses_first_depth_table():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    class FocusTarget:
        def __init__(self) -> None:
            self.focus_calls = 0

        def focus(self) -> None:
            self.focus_calls += 1

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    class FakeTabs:
        def __init__(self) -> None:
            self.active = "tab-market-depth"

    tabs = FakeTabs()
    target = FocusTarget()

    screen.query_one = lambda selector, _type=None: tabs if selector == "#portfolio-tabs" else target  # type: ignore[method-assign]

    screen._focus_current_panel()

    assert target.focus_calls == 1


def test_order_book_portfolio_panel_focuses_portfolio_table():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    class FocusTarget:
        def __init__(self) -> None:
            self.focus_calls = 0

        def focus(self) -> None:
            self.focus_calls += 1

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())

    class FakeTabs:
        def __init__(self) -> None:
            self.active = "tab-portfolio"

    tabs = FakeTabs()
    target = FocusTarget()

    screen.query_one = lambda selector, _type=None: tabs if selector == "#portfolio-tabs" else target  # type: ignore[method-assign]

    screen._focus_current_panel()

    assert target.focus_calls == 1


def test_order_book_symbol_filter_chord_applies_prefix_on_portfolio_panel():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    rerender_calls: list[str | None] = []
    statuses: list[tuple[str, str]] = []

    screen._active_panel = lambda: "tab-portfolio"  # type: ignore[method-assign]
    screen._rerender_symbol_filter_panel = lambda: rerender_calls.append(screen._symbol_prefix_filter)  # type: ignore[method-assign]
    screen._set_status = lambda message, panel="active": statuses.append((message, panel))  # type: ignore[method-assign]

    screen.on_key(type("KeyEvent", (), {"key": "k", "stop": lambda self: None})())
    screen.on_key(type("KeyEvent", (), {"key": "r", "stop": lambda self: None})())

    assert rerender_calls == ["R"]
    assert screen._symbol_prefix_filter == "R"
    assert any("Symbol filter" in message for message, _panel in statuses)


def test_order_book_symbol_filter_chord_enter_resets_prefix():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    rerender_calls: list[str | None] = []

    screen._active_panel = lambda: "tab-portfolio"  # type: ignore[method-assign]
    screen._rerender_symbol_filter_panel = lambda: rerender_calls.append(screen._symbol_prefix_filter)  # type: ignore[method-assign]
    screen._set_status = lambda _message, panel="active": None  # type: ignore[method-assign]
    screen._symbol_prefix_filter = "S"

    screen.on_key(type("KeyEvent", (), {"key": "k", "stop": lambda self: None})())
    screen.on_key(type("KeyEvent", (), {"key": "enter", "stop": lambda self: None})())

    assert rerender_calls == [None]
    assert screen._symbol_prefix_filter is None


def test_meroshare_symbol_filter_chord_applies_prefix():
    class FakeMeroShareService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

    screen = MeroSharePortfolioScreen(Path("users/meroshare_user1.json"), service=FakeMeroShareService())
    rerender_calls: list[str | None] = []
    statuses: list[str] = []

    screen._rerender_active_panel = lambda: rerender_calls.append(screen._symbol_prefix_filter)  # type: ignore[method-assign]
    screen._set_status = lambda message: statuses.append(message)  # type: ignore[method-assign]

    screen.on_key(type("KeyEvent", (), {"key": "k", "stop": lambda self: None})())
    screen.on_key(type("KeyEvent", (), {"key": "a", "stop": lambda self: None})())

    assert rerender_calls == ["A"]
    assert screen._symbol_prefix_filter == "A"
    assert any("Symbol filter" in message for message in statuses)


def test_meroshare_symbol_filter_chord_enter_resets_prefix():
    class FakeMeroShareService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

    screen = MeroSharePortfolioScreen(Path("users/meroshare_user1.json"), service=FakeMeroShareService())
    rerender_calls: list[str | None] = []

    screen._rerender_active_panel = lambda: rerender_calls.append(screen._symbol_prefix_filter)  # type: ignore[method-assign]
    screen._set_status = lambda _message: None  # type: ignore[method-assign]
    screen._symbol_prefix_filter = "S"

    screen.on_key(type("KeyEvent", (), {"key": "k", "stop": lambda self: None})())
    screen.on_key(type("KeyEvent", (), {"key": "enter", "stop": lambda self: None})())

    assert rerender_calls == [None]
    assert screen._symbol_prefix_filter is None


def test_meroshare_tabs_load_once_and_edis_checks_once():
    class FakeMeroShareService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

    screen = MeroSharePortfolioScreen(Path("users/meroshare_user1.json"), service=FakeMeroShareService())
    refresh_calls: list[str] = []
    edis_calls: list[str] = []
    focused: list[str] = []

    screen.action_refresh = lambda: refresh_calls.append(screen._active_panel())  # type: ignore[method-assign]
    screen._edis_status_worker = lambda: edis_calls.append("edis")  # type: ignore[method-assign]
    screen._focus_current_panel = lambda: focused.append(screen._active_panel())  # type: ignore[method-assign]
    screen._active_panel = lambda: "tab-meroshare-wacc"  # type: ignore[method-assign]
    fake_tabs = type("FakeTabs", (), {"active": "tab-meroshare-wacc"})()
    screen.query_one = lambda selector, _expect=None: fake_tabs if selector == "#meroshare-tabs" else None  # type: ignore[method-assign]

    screen._loaded_panels = {"tab-meroshare-wacc"}
    screen._set_panel("tab-meroshare-wacc")
    assert refresh_calls == []

    screen._loaded_panels = set()
    screen._set_panel("tab-meroshare-wacc")
    assert refresh_calls == ["tab-meroshare-wacc"]

    screen._edis_checked = False
    MeroSharePortfolioScreen._refresh_edis_status(screen)
    MeroSharePortfolioScreen._refresh_edis_status(screen)
    assert edis_calls == ["edis"]


def test_orders_screen_can_reload_store_from_disk():
    class FakeOrderStoreService:
        def __init__(self) -> None:
            self.refresh_calls = 0

        def list_rows(self):
            return []

        def refresh_store(self) -> None:
            self.refresh_calls += 1

    class FakePriceRefreshService:
        pass

    service = FakeOrderStoreService()
    screen = OrdersScreen(service=service, price_refresh_service=FakePriceRefreshService())
    reload_calls: list[str] = []
    statuses: list[str] = []

    screen.reload_table = lambda: reload_calls.append("reload")  # type: ignore[method-assign]
    screen._set_status = lambda message: statuses.append(message)  # type: ignore[method-assign]

    assert any(binding[0] == "u" and binding[1] == "refresh_store" for binding in screen.BINDINGS)

    screen.action_refresh_store()

    assert service.refresh_calls == 1
    assert reload_calls == ["reload"]
    assert statuses == ["Reloaded order store from disk."]


def test_order_editor_normalizes_just_buy_users():
    payload = [
        {"user": "users/atrad_user1.json", "quantity": 337},
        "users/atrad_user6.json",
        {"user": "users/atrad_user2.json", "quantity": None},
    ]

    assert OrderEditorScreen._normalize_just_buy_user_entries(payload) == [
        ("users/atrad_user1.json", 337),
        ("users/atrad_user6.json", None),
        ("users/atrad_user2.json", None),
    ]
