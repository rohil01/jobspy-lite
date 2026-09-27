"""Tests for Telegram notifications: gating rules and send behavior."""

import pytest

from app import notify, storage


def _job(key, score=85, match=1, status="new", notified=0, **extra):
    row = {
        "job_key": f"https://example.com/{key}",
        "title": f"Role {key}",
        "company": "Acme",
        "site": "linkedin",
        "job_url": f"https://example.com/{key}",
        "score": score,
        "experience_match": match,
        "status": status,
        "notified": notified,
        "matched_skills": ["python"],
        "missing_skills": [],
    }
    row.update(extra)
    return row


@pytest.fixture()
def seeded(temp_db):
    """Five jobs covering every gating branch."""
    jobs = [
        _job("above", score=85),
        _job("below", score=40),
        _job("nomatch", score=95, match=0),
        _job("rejected", score=90, status="rejected"),
        _job("alreadysent", score=88, notified=1),
    ]
    for row in jobs:
        storage.upsert_job(row)
    return jobs


def test_select_candidates_gating(seeded):
    candidates = notify._select_candidates(70)
    keys = [c["job_key"] for c in candidates]
    assert keys == ["https://example.com/above"]


def test_select_candidates_threshold(seeded):
    storage.upsert_job(_job("edge", score=70))
    candidates = notify._select_candidates(70)
    keys = [c["job_key"] for c in candidates]
    assert "https://example.com/above" in keys
    assert "https://example.com/edge" in keys


def test_format_alert_batches_and_truncates(seeded):
    chunks = notify.format_alert_chunks(notify._select_candidates(70))
    assert len(chunks) == 1
    assert "Role above" in chunks[0]
    assert "Acme" in chunks[0]
    huge = [_job(f"j{i}", score=90) for i in range(500)]
    chunks = notify.format_alert_chunks(huge)
    assert len(chunks) > 1, "500 jobs must span multiple Telegram messages"
    for chunk in chunks:
        assert len(chunk) <= 4100
    # Every candidate appears somewhere across the chunks — nothing dropped.
    joined = "\n".join(chunks)
    for i in (0, 199, 499):
        assert f"https://example.com/j{i}" in joined


def test_notify_marks_only_sent(seeded, monkeypatch):
    calls = {}

    def fake_send(message, token, chat):
        calls["message"] = message
        return True

    monkeypatch.setattr(notify, "send_telegram", fake_send)
    sent = notify.notify_above_threshold(70, bot_token="tok", chat_id="chat")
    assert sent == 1
    assert storage.get_job("https://example.com/above")["notified"] == 1
    # Others untouched.
    assert storage.get_job("https://example.com/below")["notified"] == 0
    assert storage.get_job("https://example.com/alreadysent")["notified"] == 1
    assert "Role above" in calls["message"]


def test_notify_unconfigured_leaves_pending(seeded, monkeypatch):
    sent = notify.notify_above_threshold(70, bot_token="", chat_id="")
    assert sent == 0
    assert storage.get_job("https://example.com/above")["notified"] == 0


def test_notify_send_failure_leaves_pending(seeded, monkeypatch):
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    sent = notify.notify_above_threshold(70, bot_token="tok", chat_id="chat")
    assert sent == 0
    assert storage.get_job("https://example.com/above")["notified"] == 0


def test_notify_no_candidates(temp_db):
    assert notify.notify_above_threshold(70, bot_token="tok", chat_id="chat") == 0


def test_all_above_threshold_are_sent(seeded, monkeypatch):
    """No top-N cap: every qualifying job goes out and gets marked."""
    for i in range(12):  # well past the old default top_n=10
        storage.upsert_job(_job(f"extra{i}", score=80 + i))
    sent_messages = []

    def fake_send(message, token, chat):
        sent_messages.append(message)
        return True

    monkeypatch.setattr(notify, "send_telegram", fake_send)
    sent = notify.notify_above_threshold(70, bot_token="tok", chat_id="chat")
    assert sent == 13  # 1 seeded above-threshold + 12 extra
    pending = storage.query(
        """
        SELECT COUNT(*) AS n FROM jobs
         WHERE score >= 70 AND experience_match = 1
           AND status != 'rejected' AND notified = 0
        """
    )
    assert pending[0]["n"] == 0
