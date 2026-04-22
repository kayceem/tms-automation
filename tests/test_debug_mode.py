from app.debug_mode import apply_debug_host_overrides
from config.models import ATRADUserConfig


def test_apply_debug_host_overrides_uses_config_values(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    config = ATRADUserConfig(
        user_id="u1",
        atrad_base_url="https://live.example",
        atrad_host="live.example",
        debug_base_url="http://127.0.0.1:8010",
        debug_host="127.0.0.1:8010",
        username="user",
        password="pass",
        account_id="acc",
    )

    updated = apply_debug_host_overrides(config)

    assert updated.atrad_base_url == "http://127.0.0.1:8010"
    assert updated.atrad_host == "127.0.0.1:8010"


def test_apply_debug_host_overrides_uses_environment_fallback(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("DEBUG_ATRAD_BASE_URL", "http://127.0.0.1:8011")
    monkeypatch.setenv("DEBUG_ATRAD_HOST", "127.0.0.1:8011")
    config = ATRADUserConfig(
        user_id="u1",
        atrad_base_url="https://live.example",
        atrad_host="live.example",
        username="user",
        password="pass",
        account_id="acc",
    )

    updated = apply_debug_host_overrides(config)

    assert updated.atrad_base_url == "http://127.0.0.1:8011"
    assert updated.atrad_host == "127.0.0.1:8011"
