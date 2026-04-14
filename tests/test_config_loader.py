from argparse import Namespace
import json

import pytest

from app.config_loader import load_fetch_user_configs, load_trader_config, load_user_config
from config import ATRADUserConfig, UserConfig
from config.models import UserConfigManager


def write_config(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_user_config_detects_tms_and_sets_file_path(tmp_path):
    write_config(
        tmp_path / "default.json",
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    config_path = tmp_path / "user.json"
    write_config(
        config_path,
        {
            "user_id": "tms-user",
            "tms_host": "example.test",
            "tms_base_url": "https://example.test",
            "xsrf_token": "xsrf-token",
            "rid_cookie": "rid-cookie",
            "host_session_id": "host-session",
            "access_token": "access-token",
            "request_owner": "owner",
            "member_code": "123",
        },
    )

    config = load_user_config(Namespace(user_config=str(config_path)))

    assert isinstance(config, UserConfig)
    assert config.user_id == "tms-user"
    assert config._config_file_path == str(config_path)
    assert config.trigger_mode_poll_interval_ms == 8
    assert config.trigger_mode_refresh_interval_seconds == 60
    assert config.trigger_sell_poll_interval_ms == 250
    assert config.trigger_mode_slow_poll_interval_ms == 250
    assert config.trigger_mode_requests_per_fetch_user == 2
    assert config.trigger_mode_parallel_fetch_enabled is True
    assert config.trigger_mode_parallel_spawn_interval_ms == 12
    assert config.trigger_mode_parallel_cycle_timeout_ms == 24
    assert config.trigger_mode_parallel_wait is True


def test_load_trader_config_detects_atrad(tmp_path):
    write_config(
        tmp_path / "default.json",
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    config_path = tmp_path / "seller.json"
    write_config(
        config_path,
        {
            "system": "atrad",
            "user_id": "atrad-user",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "demo-user",
            "password": "demo-pass",
            "account_id": "ACC-1",
        },
    )

    config = load_trader_config(str(config_path), "seller")

    assert isinstance(config, ATRADUserConfig)
    assert config.user_id == "atrad-user"
    assert config._config_file_path == str(config_path)
    assert config.trigger_mode_poll_interval_ms == 8
    assert config.trigger_mode_refresh_interval_seconds == 60
    assert config.trigger_sell_poll_interval_ms == 250
    assert config.trigger_mode_slow_poll_interval_ms == 250
    assert config.trigger_mode_requests_per_fetch_user == 2
    assert config.trigger_mode_parallel_fetch_enabled is True
    assert config.trigger_mode_parallel_spawn_interval_ms == 12
    assert config.trigger_mode_parallel_cycle_timeout_ms == 24
    assert config.trigger_mode_parallel_wait is True


def test_load_fetch_user_configs_skips_invalid_entries_but_keeps_valid_ones(tmp_path):
    valid_path = tmp_path / "fetch-1.json"
    invalid_path = tmp_path / "fetch-bad.json"
    write_config(
        valid_path,
        {
            "user_id": "fetch-user",
            "tms_host": "example.test",
            "tms_base_url": "https://example.test",
            "xsrf_token": "xsrf-token",
            "rid_cookie": "rid-cookie",
            "host_session_id": "host-session",
            "access_token": "access-token",
            "request_owner": "owner",
            "member_code": "123",
        },
    )
    write_config(invalid_path, {"user_id": "broken"})

    args = Namespace(fetch_user=None, fetch_users=[str(valid_path), str(invalid_path)], atrad_fetch=False)
    configs, is_atrad_fetch = load_fetch_user_configs(args)

    assert is_atrad_fetch is False
    assert [config.user_id for config in configs] == ["fetch-user"]


def test_load_fetch_user_configs_raises_when_all_entries_are_invalid(tmp_path):
    invalid_path = tmp_path / "fetch-bad.json"
    write_config(invalid_path, {"user_id": "broken"})

    args = Namespace(fetch_user=None, fetch_users=[str(invalid_path)], atrad_fetch=False)

    with pytest.raises(ValueError, match="No valid fetch user configurations loaded"):
        load_fetch_user_configs(args)


def test_user_config_inherits_trigger_defaults_from_sibling_default_json(tmp_path):
    default_path = tmp_path / "default.json"
    user_path = tmp_path / "user.json"

    write_config(
        default_path,
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    write_config(
        user_path,
        {
            "user_id": "tms-user",
            "tms_host": "example.test",
            "tms_base_url": "https://example.test",
            "xsrf_token": "xsrf-token",
            "rid_cookie": "rid-cookie",
            "host_session_id": "host-session",
            "access_token": "access-token",
            "request_owner": "owner",
            "member_code": "123",
            "trigger_sell_poll_interval_ms": 300,
        },
    )

    config = UserConfig.from_file(str(user_path))

    assert config.trigger_mode_poll_interval_ms == 8
    assert config.trigger_mode_refresh_interval_seconds == 60
    assert config.trigger_sell_poll_interval_ms == 300
    assert config.trigger_mode_slow_poll_interval_ms == 250
    assert config.trigger_mode_requests_per_fetch_user == 2
    assert config.trigger_mode_parallel_fetch_enabled is True
    assert config.trigger_mode_parallel_spawn_interval_ms == 12
    assert config.trigger_mode_parallel_cycle_timeout_ms == 24
    assert config.trigger_mode_parallel_wait is True


def test_atrad_config_inherits_trigger_defaults_from_sibling_default_json(tmp_path):
    default_path = tmp_path / "default.json"
    user_path = tmp_path / "atrad-user.json"

    write_config(
        default_path,
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    write_config(
        user_path,
        {
            "system": "atrad",
            "user_id": "atrad-user",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "demo-user",
            "password": "demo-pass",
            "account_id": "ACC-1",
        },
    )

    config = ATRADUserConfig.from_file(str(user_path))

    assert config.trigger_mode_poll_interval_ms == 8
    assert config.trigger_mode_refresh_interval_seconds == 60
    assert config.trigger_sell_poll_interval_ms == 250
    assert config.trigger_mode_slow_poll_interval_ms == 250
    assert config.trigger_mode_requests_per_fetch_user == 2
    assert config.trigger_mode_parallel_fetch_enabled is True
    assert config.trigger_mode_parallel_spawn_interval_ms == 12
    assert config.trigger_mode_parallel_cycle_timeout_ms == 24
    assert config.trigger_mode_parallel_wait is True


def test_user_config_manager_skips_default_json_when_loading_directory(tmp_path):
    write_config(
        tmp_path / "default.json",
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    write_config(
        tmp_path / "user.json",
        {
            "user_id": "tms-user",
            "tms_host": "example.test",
            "tms_base_url": "https://example.test",
            "xsrf_token": "xsrf-token",
            "rid_cookie": "rid-cookie",
            "host_session_id": "host-session",
            "access_token": "access-token",
            "request_owner": "owner",
            "member_code": "123",
        },
    )

    manager = UserConfigManager()
    manager.load_users_from_directory(str(tmp_path))

    assert manager.user_count() == 1
    assert manager.get_user("tms-user") is not None


def test_user_config_save_does_not_persist_inherited_default_keys(tmp_path):
    default_path = tmp_path / "default.json"
    user_path = tmp_path / "user.json"

    write_config(
        default_path,
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    write_config(
        user_path,
        {
            "user_id": "tms-user",
            "tms_host": "example.test",
            "tms_base_url": "https://example.test",
            "xsrf_token": "xsrf-token",
            "rid_cookie": "rid-cookie",
            "host_session_id": "host-session",
            "access_token": "access-token",
            "request_owner": "owner",
            "member_code": "123",
        },
    )

    config = UserConfig.from_file(str(user_path))
    config.update_cookies(access_token="new-access-token")

    persisted = json.loads(user_path.read_text(encoding="utf-8"))
    assert persisted["access_token"] == "new-access-token"
    assert "trigger_mode_poll_interval_ms" not in persisted
    assert "trigger_mode_refresh_interval_seconds" not in persisted
    assert "trigger_sell_poll_interval_ms" not in persisted
    assert "trigger_mode_slow_poll_interval_ms" not in persisted
    assert "trigger_mode_requests_per_fetch_user" not in persisted
    assert "trigger_mode_parallel_fetch_enabled" not in persisted
    assert "trigger_mode_parallel_spawn_interval_ms" not in persisted
    assert "trigger_mode_parallel_cycle_timeout_ms" not in persisted
    assert "trigger_mode_parallel_wait" not in persisted


def test_atrad_config_save_does_not_persist_inherited_default_keys(tmp_path):
    default_path = tmp_path / "default.json"
    user_path = tmp_path / "atrad-user.json"

    write_config(
        default_path,
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_sell_poll_interval_ms": 250,
            "trigger_mode_slow_poll_interval_ms": 250,
            "trigger_mode_requests_per_fetch_user": 2,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_spawn_interval_ms": 12,
            "trigger_mode_parallel_cycle_timeout_ms": 24,
            "trigger_mode_parallel_wait": True,
        },
    )
    write_config(
        user_path,
        {
            "system": "atrad",
            "user_id": "atrad-user",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "demo-user",
            "password": "demo-pass",
            "account_id": "ACC-1",
        },
    )

    config = ATRADUserConfig.from_file(str(user_path))
    config.update_session(session_id="session-1", cookies={"JSESSIONID": "session-1"})
    config.save_session()

    persisted = json.loads(user_path.read_text(encoding="utf-8"))
    assert persisted["_cookies"]["JSESSIONID"] == "session-1"
    assert "trigger_mode_poll_interval_ms" not in persisted
    assert "trigger_mode_refresh_interval_seconds" not in persisted
    assert "trigger_sell_poll_interval_ms" not in persisted
    assert "trigger_mode_slow_poll_interval_ms" not in persisted
    assert "trigger_mode_requests_per_fetch_user" not in persisted
    assert "trigger_mode_parallel_fetch_enabled" not in persisted
    assert "trigger_mode_parallel_spawn_interval_ms" not in persisted
    assert "trigger_mode_parallel_cycle_timeout_ms" not in persisted
    assert "trigger_mode_parallel_wait" not in persisted
