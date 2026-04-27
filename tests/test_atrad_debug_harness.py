import json
from argparse import Namespace

from utils.atrad_debug_harness import build_main_command, build_scenarios


def test_build_scenarios_splits_multi_queue_trigger_sell_queue_and_single_orders(tmp_path):
    store_path = tmp_path / "order_store.json"
    store_path.write_text(
        json.dumps(
            {
                "orders": [
                    {
                        "id": "mq-1",
                        "execute": True,
                        "success": False,
                        "queue_id": 1,
                        "ticker": "AAA",
                        "mode": "ipo-trigger",
                        "multi_queue": True,
                    },
                    {
                        "id": "mq-2",
                        "execute": True,
                        "success": False,
                        "queue_id": 1,
                        "ticker": "BBB",
                        "mode": "ipo-trigger",
                        "multi_queue": True,
                    },
                    {
                        "id": "ts-1",
                        "execute": True,
                        "success": False,
                        "queue_id": 2,
                        "ticker": "CCC",
                        "mode": "trigger-sell",
                        "trigger_sell_queue": True,
                    },
                    {
                        "id": "ts-2",
                        "execute": True,
                        "success": False,
                        "queue_id": 2,
                        "ticker": "DDD",
                        "mode": "trigger-sell",
                        "trigger_sell_queue": True,
                    },
                    {
                        "id": "single-1",
                        "execute": True,
                        "success": False,
                        "queue_id": 3,
                        "ticker": "EEE",
                        "mode": "normal",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    scenarios = build_scenarios(str(store_path), include_full_store=True)

    assert [scenario.name for scenario in scenarios] == [
        "full_store",
        "queue_01_multi_queue",
        "queue_02_trigger_sell_queue",
        "queue_03_single-1",
    ]


def test_build_main_command_uses_pool_users_without_fetch_flags(tmp_path):
    scenario_store = tmp_path / "scenario_store.json"
    args = Namespace(
        user_config=None,
        pool_users=["users/u1.json", "users/u2.json"],
        fetch_users=["users/fetch1.json"],
        just_buy_users=["users/jb1.json"],
        atrad_fetch=True,
    )

    command = build_main_command(args, scenario_store)

    assert "--pool-users" in command
    assert "--user-config" not in command
    assert "--fetch-users" not in command
    assert "--just-buy-users" not in command
    assert "--atrad-fetch" not in command


def test_build_main_command_uses_user_and_fetch_flags_when_not_pooled(tmp_path):
    scenario_store = tmp_path / "scenario_store.json"
    args = Namespace(
        user_config="users/main.json",
        pool_users=None,
        fetch_users=["users/fetch1.json", "users/fetch2.json"],
        just_buy_users=["users/jb1.json"],
        atrad_fetch=True,
    )

    command = build_main_command(args, scenario_store)

    assert "--user-config" in command
    assert "--fetch-users" in command
    assert "--just-buy-users" in command
    assert "--atrad-fetch" in command
