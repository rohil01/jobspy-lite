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


def test_hours_are_in_config_timezone_not_server_time(clean_settings):
    """The 8-22 window must be evaluated in the CONFIG tz (Asia/Kolkata),
    not the server's local zone — UTC evaluation let runs fire at night IST."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cfg = {**scheduler.get_config(), "timezone": "Asia/Kolkata",
           "interval_minutes": 110, "active_from": 8, "active_to": 22}
    now_ist_hour = datetime.now(ZoneInfo("Asia/Kolkata")).hour
    assert scheduler._hour_window_ok(cfg, now_ist_hour) == (8 <= now_ist_hour < 22)

    # Interval ticks anchor to the window start in config tz.
    trigger = scheduler._build_trigger(cfg)
    nxt = trigger.get_next_fire_time(None, datetime.now(ZoneInfo("UTC")))
    local_hour = nxt.astimezone(ZoneInfo("Asia/Kolkata")).hour
    assert 8 <= local_hour < 22, f"next fire {nxt} outside 8-22 IST"


def test_interval_reanchors_daily(clean_settings):
    """With interval 110 and window 8-22 the chain must be exactly
    8:00, 9:50, 11:40 … 20:50 IST each day, re-anchored — never drifting."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    cfg = {**scheduler.get_config(), "mode": "interval",
           "timezone": "Asia/Kolkata", "interval_minutes": 110,
           "active_from": 8, "active_to": 22}
    trig = scheduler._build_trigger(cfg)

    sim = datetime(2026, 9, 28, 2, 20, tzinfo=timezone.utc)  # 07:50 IST
    fires = []
    prev = None
    for _ in range(12):
        prev = trig.get_next_fire_time(prev, sim if prev is None else prev + timedelta(seconds=1))
        fires.append(prev.astimezone(ZoneInfo("Asia/Kolkata")))

    by_day = {}
    for f in fires:
        by_day.setdefault(f.date(), []).append(f.strftime("%H:%M"))
    day1, day2 = list(by_day.values())[0], list(by_day.values())[1]
    assert day1[0] == "08:00" and day1[1] == "09:50" and day1[2] == "11:40"
    assert day1[-1] == "20:50", f"last fire before window end: {day1[-1]}"
    assert day2[0] == "08:00", "next day must re-anchor to 8:00, not drift"


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
