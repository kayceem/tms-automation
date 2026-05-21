import json

import pytest

from utils.order_store import OrderStore


def write_store(path, orders):
    path.write_text(json.dumps({"orders": orders}, indent=2), encoding="utf-8")


def test_get_executable_orders_filters_successful_and_sorts_by_queue_id(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {"id": "b", "ticker": "bbb", "price": 200, "quantity": 20, "mode": "normal", "execute": True, "queue_id": 3},
            {"id": "a", "ticker": "aaa", "price": 100, "quantity": 10, "mode": "normal", "execute": True, "queue_id": 1},
            {"id": "done", "ticker": "ccc", "price": 300, "quantity": 30, "mode": "normal", "execute": False, "success": True},
        ],
    )

    store = OrderStore(str(store_path))
    executable = store.get_executable_orders()

    assert [order["id"] for order in executable] == ["a", "b"]
    assert executable[0]["ticker"] == "aaa"
    assert executable[0]["queue_id"] == 1
    assert executable[1]["queue_id"] == 3


def test_get_executable_orders_rejects_successful_orders_still_marked_execute(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {"id": "already-done", "ticker": "AAA", "price": 100, "quantity": 10, "mode": "normal", "execute": True, "success": True},
        ],
    )

    store = OrderStore(str(store_path))

    with pytest.raises(ValueError, match="already succeeded"):
        store.get_executable_orders()


def test_validate_order_rejects_just_buy_without_no_ladder(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(store_path, [])
    store = OrderStore(str(store_path))

    with pytest.raises(ValueError, match="just_buy can only be used with no_ladder=true"):
        store.validate_order(
            {
                "id": "bad-order",
                "ticker": "AAA",
                "price": 100,
                "quantity": 10,
                "mode": "ipo-trigger",
                "just_buy": True,
            }
        )


def test_validate_order_normalizes_ipo_sell_buy_trigger_fields(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(store_path, [])
    store = OrderStore(str(store_path))

    order = store.validate_order(
        {
            "id": "sell-buy",
            "ticker": "nabil",
            "price": "500",
            "quantity": "10",
            "mode": "ipo-sell-buy-trigger",
            "seller_config": "users/seller.json",
            "buyer_config": "users/buyer.json",
            "sell_quantity": "5",
        }
    )

    assert order["ticker"] == "NABIL"
    assert order["sell_quantity"] == 5
    assert order["sell_pre_wait_ms"] == 5000
    assert order["queue_id"] == 999


def test_validate_order_normalizes_just_buy_users(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(store_path, [])
    store = OrderStore(str(store_path))

    order = store.validate_order(
        {
            "id": "just-buy-users",
            "ticker": "nabil",
            "price": "500",
            "quantity": "10",
            "mode": "ipo-trigger",
            "no_ladder": True,
            "just_buy": True,
            "just_buy_users": [
                {"user": " users/jb1.json ", "quantity": "337"},
                "users/jb2.json",
            ],
        }
    )

    assert order["just_buy_users"] == [
        {"user": "users/jb1.json", "quantity": 337},
        "users/jb2.json",
    ]


def test_validate_order_accepts_trigger_sell_queue_for_trigger_sell(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(store_path, [])
    store = OrderStore(str(store_path))

    order = store.validate_order(
        {
            "id": "sell-queue",
            "ticker": "nabil",
            "price": "500",
            "quantity": "10",
            "mode": "trigger-sell",
            "trigger_sell_queue": True,
        }
    )

    assert order["trigger_sell_queue"] is True


def test_get_order_summary_includes_user_id(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {
                "id": "hfin_sell",
                "ticker": "HFIN",
                "price": 1320,
                "quantity": 100,
                "mode": "trigger-sell",
                "execute": False,
                "success": False,
                "user_id": "atrad_user1",
                "queue_id": 1,
            },
            {
                "id": "skhel_sell",
                "ticker": "SKHEL",
                "price": 1750,
                "quantity": 100,
                "mode": "trigger-sell",
                "execute": True,
                "success": False,
                "user_id": "atrad_user6",
                "queue_id": 1,
            },
        ],
    )

    summary = OrderStore(str(store_path)).get_order_summary()

    assert "atrad_user1" in summary
    assert "atrad_user6" in summary
    assert "trigger-sell" in summary


def test_validate_order_rejects_trigger_sell_queue_for_non_trigger_sell(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(store_path, [])
    store = OrderStore(str(store_path))

    with pytest.raises(ValueError, match="trigger_sell_queue requires mode='trigger-sell'"):
        store.validate_order(
            {
                "id": "bad-sell-queue",
                "ticker": "AAA",
                "price": 100,
                "quantity": 10,
                "mode": "normal",
                "trigger_sell_queue": True,
            }
        )


def test_get_executable_orders_rejects_inconsistent_multi_queue_group(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {
                "id": "mq-1",
                "ticker": "AAA",
                "price": 100,
                "quantity": 10,
                "mode": "ipo-trigger",
                "execute": True,
                "queue_id": 1,
                "multi_queue": True,
                "no_ladder": True,
            },
            {
                "id": "mq-2",
                "ticker": "BBB",
                "price": 101,
                "quantity": 11,
                "mode": "ipo-trigger",
                "execute": True,
                "queue_id": 1,
                "multi_queue": False,
                "no_ladder": True,
            },
        ],
    )

    store = OrderStore(str(store_path))

    with pytest.raises(ValueError, match="inconsistent multi_queue values"):
        store.get_executable_orders()


def test_mark_success_persists_state(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {"id": "done", "ticker": "AAA", "price": 100, "quantity": 10, "mode": "normal", "execute": True},
        ],
    )

    store = OrderStore(str(store_path))
    store.mark_success("done")

    persisted = json.loads(store_path.read_text(encoding="utf-8"))
    assert persisted["orders"][0]["success"] is True
    assert persisted["orders"][0]["execute"] is False


def test_add_order_persists_validated_order(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(store_path, [])

    store = OrderStore(str(store_path))
    added = store.add_order(
        {
            "id": "new-order",
            "ticker": "nabil",
            "price": "500",
            "quantity": "10",
            "mode": "normal",
            "execute": True,
        }
    )

    assert added["ticker"] == "NABIL"
    persisted = json.loads(store_path.read_text(encoding="utf-8"))
    assert persisted["orders"][0]["id"] == "new-order"
    assert persisted["orders"][0]["execute"] is True


def test_update_order_preserves_unrelated_metadata(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {
                "id": "existing",
                "ticker": "AAA",
                "price": 100,
                "quantity": 10,
                "mode": "normal",
                "note": "keep-me",
                "execute": True,
            },
        ],
    )

    store = OrderStore(str(store_path))
    updated = store.update_order("existing", {"price": 150, "quantity": 15})

    assert updated["price"] == 150.0
    assert updated["quantity"] == 15
    assert updated["note"] == "keep-me"
    persisted = json.loads(store_path.read_text(encoding="utf-8"))
    assert persisted["orders"][0]["note"] == "keep-me"


def test_remove_order_deletes_target_order(tmp_path):
    store_path = tmp_path / "order_store.json"
    write_store(
        store_path,
        [
            {"id": "remove-me", "ticker": "AAA", "price": 100, "quantity": 10, "mode": "normal"},
            {"id": "keep-me", "ticker": "BBB", "price": 200, "quantity": 20, "mode": "normal"},
        ],
    )

    store = OrderStore(str(store_path))
    removed = store.remove_order("remove-me")

    assert removed["id"] == "remove-me"
    persisted = json.loads(store_path.read_text(encoding="utf-8"))
    assert [order["id"] for order in persisted["orders"]] == ["keep-me"]
