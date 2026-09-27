"""Scheduler config validation and trigger construction tests."""

import pytest

from app import scheduler, storage


def test_default_config(clean_settings):
    config = scheduler.get_config()
    assert config["mode"] == "interval"
    assert config["enabled"] is False


def test_validate_interval_mode():
    assert scheduler.validate_config({"mode": "interval", "interval_minutes": 30}) is None
    assert ">= 5" in scheduler.validate_config({"mode": "interval", "interval_minutes": 2})
    err = scheduler.validate_config({"mode": "interval", "interval_minutes": 30, "active_from": 22, "active_to": 8})
    assert err is not None  # from must be < to
    assert scheduler.validate_config({"mode": "bogus"}) is not None


def test_validate_cron_mode():
    assert scheduler.validate_config({"mode": "cron", "cron_expression": "0 */2 * * *"}) is None
    assert scheduler.validate_config({"mode": "cron", "cron_expression": "garbage"}) is not None
    assert scheduler.validate_config({"mode": "cron"}) is not None  # missing expression


def test_set_config_persists_and_applies(clean_settings):
    merged = scheduler.set_config({"mode": "cron", "cron_expression": "30 9 * * *"})
    assert merged["cron_expression"] == "30 9 * * *"
    assert storage.get_setting("scheduler_config")["mode"] == "cron"
    # Not running yet: applying is a no-op but must not raise.
    scheduler.apply_config(merged)
    scheduler.stop()


def test_start_stop_and_status(clean_settings):
    scheduler.set_config({"mode": "interval", "interval_minutes": 60})
    scheduler.start()
    status = scheduler.status()
    assert status["running"] is True
    assert status["next_run_at"] is not None
    assert scheduler.is_healthy() is True
    scheduler.stop()
    status = scheduler.status()
    assert status["running"] is False
    assert scheduler.is_healthy() is False


def test_toggle_persists_enabled(clean_settings):
    try:
        merged = scheduler.toggle(True)
        assert merged["enabled"] is True
        assert scheduler.status()["running"] is True
    finally:
        scheduler.toggle(False)
    assert storage.get_setting("scheduler_config")["enabled"] is False
    assert scheduler.status()["running"] is False


def test_hour_window_gate(clean_settings):
    config = {"mode": "interval", "active_from": 8, "active_to": 22}
    assert scheduler._hour_window_ok(config, 9) is True
    assert scheduler._hour_window_ok(config, 23) is False
    assert scheduler._hour_window_ok(config, 8) is True
    # Open-ended window (to == 24) allows the end hour itself.
    config_open = {"mode": "interval", "active_from": 8, "active_to": 24}
    assert scheduler._hour_window_ok(config_open, 23) is True
    # Cron mode ignores the window entirely.
    config_cron = {"mode": "cron", "active_from": 8, "active_to": 22}
    assert scheduler._hour_window_ok(config_cron, 3) is True
