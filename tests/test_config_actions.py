import json

import pytest

from utils.config.atrad_config_actions import (
    load_default_trigger_settings,
    reset_atrad_jsession_ids,
    save_default_trigger_settings,
    set_atrad_numeric_key,
)


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_reset_atrad_jsession_ids_only_updates_atrad_user_files(tmp_path):
    write_json(
        tmp_path / "atrad_user1.json",
        {
            "system": "atrad",
            "_cookies": {"JSESSIONID": "abc", "theme": "black"},
        },
    )
    write_json(
        tmp_path / "user1.json",
        {
            "user_id": "tms-user",
            "_cookies": {"JSESSIONID": "leave-alone"},
        },
    )

    results = reset_atrad_jsession_ids(tmp_path)

    assert [result.path.name for result in results] == ["atrad_user1.json"]
    atrad_payload = json.loads((tmp_path / "atrad_user1.json").read_text(encoding="utf-8"))
    tms_payload = json.loads((tmp_path / "user1.json").read_text(encoding="utf-8"))
    assert atrad_payload["_cookies"]["JSESSIONID"] == ""
    assert atrad_payload["_cookies"]["theme"] == "black"
    assert tms_payload["_cookies"]["JSESSIONID"] == "leave-alone"


def test_save_default_trigger_settings_creates_default_json(tmp_path):
    result = save_default_trigger_settings(
        {
            "trigger_mode_poll_interval_ms": 8,
            "trigger_mode_refresh_interval_seconds": 60,
            "trigger_mode_parallel_fetch_enabled": True,
            "trigger_mode_parallel_wait": False,
        },
        tmp_path,
    )

    assert result.path == tmp_path / "default.json"
    persisted = load_default_trigger_settings(tmp_path)
    assert persisted["trigger_mode_poll_interval_ms"] == 8
    assert persisted["trigger_mode_refresh_interval_seconds"] == 60
    assert persisted["trigger_mode_parallel_fetch_enabled"] is True
    assert persisted["trigger_mode_parallel_wait"] is False


def test_save_default_trigger_settings_rejects_invalid_values(tmp_path):
    with pytest.raises(ValueError, match="must be greater than 0"):
        save_default_trigger_settings(
            {"trigger_mode_poll_interval_ms": 0},
            tmp_path,
        )


def test_save_default_trigger_settings_rejects_invalid_boolean_values(tmp_path):
    with pytest.raises(ValueError, match="must be a boolean"):
        save_default_trigger_settings(
            {"trigger_mode_parallel_fetch_enabled": "maybe"},
            tmp_path,
        )


def test_set_atrad_numeric_key_updates_matching_files(tmp_path):
    write_json(tmp_path / "atrad_user1.json", {"system": "atrad", "user_id": "a"})
    write_json(tmp_path / "atrad_user2.json", {"atrad_base_url": "https://atrad.test", "user_id": "b"})

    results = set_atrad_numeric_key("trigger_mode_poll_interval_ms", 25, tmp_path)

    assert len(results) == 2
    payload_one = json.loads((tmp_path / "atrad_user1.json").read_text(encoding="utf-8"))
    payload_two = json.loads((tmp_path / "atrad_user2.json").read_text(encoding="utf-8"))
    assert payload_one["trigger_mode_poll_interval_ms"] == 25
    assert payload_two["trigger_mode_poll_interval_ms"] == 25
