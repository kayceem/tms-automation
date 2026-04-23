import json

from utils.atrad_debug_server import DebugServerState, TickerProfile, build_profiles_from_order_store


def test_build_profiles_from_order_store_uses_fourth_highest_level_and_doubles_multi_queue(tmp_path):
    store_path = tmp_path / "order_store.json"
    store_path.write_text(
        json.dumps(
            {
                "orders": [
                    {
                        "id": "mq-1",
                        "ticker": "NABIL",
                        "price": 500,
                        "quantity": 10,
                        "mode": "ipo-trigger",
                        "limit": 550,
                        "no_ladder": True,
                        "just_buy": True,
                        "multi_queue": True,
                        "execute": True,
                    },
                    {
                        "id": "mq-2",
                        "ticker": "NABIL",
                        "price": 500,
                        "quantity": 10,
                        "mode": "ipo-trigger",
                        "limit": 550,
                        "no_ladder": True,
                        "multi_queue": True,
                        "execute": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    profiles = build_profiles_from_order_store(str(store_path), base_requests_per_step=100)

    profile = profiles["NABIL"]
    assert profile.price_levels == [500.0, 515.0, 530.4, 546.3, 562.6, 579.4, 632.5]
    assert profile.start_level_index == 3
    assert profile.current_price() == 546.3
    assert profile.requests_per_step == 200
    assert profile.is_multi_queue is True
    assert profile.just_buy_enabled is True


def test_build_profiles_from_order_store_marks_non_just_buy_tickers(tmp_path):
    store_path = tmp_path / "order_store.json"
    store_path.write_text(
        json.dumps(
            {
                "orders": [
                    {
                        "id": "normal-1",
                        "ticker": "NHPC",
                        "price": 300,
                        "quantity": 5,
                        "mode": "ipo-trigger",
                        "limit": 330,
                        "no_ladder": True,
                        "just_buy": False,
                        "execute": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    profiles = build_profiles_from_order_store(str(store_path), base_requests_per_step=100)

    assert profiles["NHPC"].just_buy_enabled is False


def test_debug_server_state_resets_all_profiles_after_inactivity():
    fallback = TickerProfile(
        symbol="DEFAULT",
        price_levels=[100.0, 101.0],
        start_level_index=0,
        requests_per_step=10,
        request_count=3,
        order_request_count=2,
    )
    profile = TickerProfile(
        symbol="NABIL",
        price_levels=[500.0, 515.0],
        start_level_index=0,
        requests_per_step=100,
        request_count=9,
        order_request_count=4,
    )
    state = DebugServerState(
        min_delay_ms=6.0,
        max_delay_ms=15.0,
        broker_code="DBG",
        watch_id=77,
        fallback_profile=fallback,
        ticker_profiles={"NABIL": profile},
        inactivity_reset_seconds=5.0,
        last_request_monotonic=10.0,
    )

    state.note_request(now=14.0)
    assert fallback.request_count == 3
    assert profile.request_count == 9

    state.note_request(now=20.0)
    assert fallback.request_count == 0
    assert fallback.order_request_count == 0
    assert profile.request_count == 0
    assert profile.order_request_count == 0
