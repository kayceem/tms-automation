import pytest

from app.pool_users import UserPool, load_user_pool, validate_pool_orders


class DummyConfig:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id


class DummyATRADConfig(DummyConfig):
    pass


def test_load_user_pool_rejects_duplicate_user_ids(monkeypatch):
    configs = {
        "u1.json": DummyConfig("same-user"),
        "u2.json": DummyConfig("same-user"),
    }

    monkeypatch.setattr("app.pool_users.load_config_by_system", lambda path, _label: configs[path])

    with pytest.raises(ValueError, match="Duplicate pooled user_id 'same-user'"):
        load_user_pool(["u1.json", "u2.json"])


def test_load_user_pool_rejects_mixed_platforms(monkeypatch):
    configs = {
        "u1.json": DummyConfig("tms-user"),
        "u2.json": DummyATRADConfig("atrad-user"),
    }

    monkeypatch.setattr("app.pool_users.load_config_by_system", lambda path, _label: configs[path])
    monkeypatch.setattr("app.pool_users.ATRADUserConfig", DummyATRADConfig)

    with pytest.raises(ValueError, match="same platform"):
        load_user_pool(["u1.json", "u2.json"])


def test_validate_pool_orders_requires_user_ids_and_known_users():
    pool = UserPool(
        users_by_id={"main-a": DummyConfig("main-a"), "main-b": DummyConfig("main-b")},
        ordered_users=[DummyConfig("main-a"), DummyConfig("main-b")],
        is_atrad=False,
    )

    with pytest.raises(ValueError, match="missing required field 'user_id'"):
        validate_pool_orders(
            [
                {
                    "id": "order-1",
                    "mode": "normal",
                    "queue_id": 1,
                    "multi_queue": False,
                }
            ],
            pool,
        )

    with pytest.raises(ValueError, match="unknown pooled user_id 'missing-user'"):
        validate_pool_orders(
            [
                {
                    "id": "order-1",
                    "mode": "normal",
                    "queue_id": 1,
                    "multi_queue": False,
                    "user_id": "missing-user",
                }
            ],
            pool,
        )


def test_validate_pool_orders_rejects_ipo_sell_buy_trigger():
    pool = UserPool(
        users_by_id={"main-a": DummyConfig("main-a"), "main-b": DummyConfig("main-b")},
        ordered_users=[DummyConfig("main-a"), DummyConfig("main-b")],
        is_atrad=False,
    )

    with pytest.raises(ValueError, match="incompatible with --pool-users"):
        validate_pool_orders(
            [
                {
                    "id": "order-1",
                    "mode": "ipo-sell-buy-trigger",
                    "queue_id": 1,
                    "multi_queue": False,
                    "user_id": "main-a",
                }
            ],
            pool,
        )
