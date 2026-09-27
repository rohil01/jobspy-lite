"""Tests for the SQLite storage layer."""

import pytest

from app import storage


def _job(key="u1", **overrides):
    base = {
        "title": "AI Engineer",
        "company": "Acme",
        "location": "Bengaluru",
        "site": "linkedin",
        "job_url": f"https://example.com/{key}",
        "description": "Build things",
    }
    base.update(overrides)
    return base


def test_raw_rescape_keeps_stored_ai_results(temp_db):
    """Re-scraping a scored job must NOT wipe its score back to unscored —
    that bug made the AI agent re-run on every job every run."""
    key = storage.upsert_job(_job())
    storage.upsert_job(
        _job(
            score=91,
            final_score=91,
            verdict="strong",
            matched_skills=["python"],
            missing_skills=["sql"],
            reasoning="great fit",
            required_years={"min": 1, "max": 3},
            experience_match=True,
            scored_with_resume="hash1",
        )
    )

    # Raw re-scrape of the same posting (fresh listing data, no AI fields).
    storage.upsert_job(_job(description="Updated description v2"))

    job = storage.get_job(key)
    assert job["score"] == 91
    assert job["verdict"] == "strong"
    assert job["matched_skills"] == ["python"]
    assert job["required_years_min"] == 1
    assert job["scored_with_resume"] == "hash1"
    assert job["description"] == "Updated description v2"  # listing data refreshed
    assert job["scored_at"] is not None


def test_upsert_insert_and_preserves_user_state(temp_db):
    key = storage.upsert_job(_job())

    # User accepts the job...
    assert storage.set_job_status(key, "accepted") is True

    # ...then a re-scrape upserts the same posting: status must survive.
    storage.upsert_job(_job(score=88, verdict="strong"))
    job = storage.get_job(key)
    assert job["status"] == "accepted"
    assert job["score"] == 88
    assert job["verdict"] == "strong"


def test_upsert_new_and_last_seen(temp_db):
    key = storage.upsert_job(_job())
    first = storage.get_job(key)
    assert first["first_seen_at"] == first["last_seen_at"]
    assert first["status"] == "new"


def test_list_jobs_orders_by_score(temp_db):
    storage.upsert_job(_job("a", score=50))
    storage.upsert_job(_job("b", score=90))
    storage.upsert_job(_job("c", score=70))
    jobs = storage.list_jobs()
    assert [j["job_key"] for j in jobs] == ["https://example.com/b", "https://example.com/c", "https://example.com/a"]


def test_list_jobs_status_filter(temp_db):
    k1 = storage.upsert_job(_job("a"))
    storage.upsert_job(_job("b"))
    storage.set_job_status(k1, "rejected")
    assert [j["job_key"] for j in storage.list_jobs(status="rejected")] == [k1]
    assert len(storage.list_jobs(status="new")) == 1


def test_counts_by_status(temp_db):
    k1 = storage.upsert_job(_job("a", score=80))
    storage.upsert_job(_job("b", score=60))
    storage.set_job_status(k1, "accepted")
    counts = storage.counts_by_status()
    assert counts["total"] == 2
    assert counts["accepted"] == 1
    assert counts["new"] == 1
    assert counts["avg_score"] == 70.0


def test_invalid_status_raises(temp_db):
    key = storage.upsert_job(_job())
    with pytest.raises(ValueError):
        storage.set_job_status(key, "maybe")


def test_mark_notified(temp_db):
    k1 = storage.upsert_job(_job("a"))
    k2 = storage.upsert_job(_job("b"))
    storage.mark_notified([k1])
    assert storage.get_job(k1)["notified"] == 1
    assert storage.get_job(k2)["notified"] == 0


def test_settings_roundtrip(temp_db):
    storage.set_setting("score_threshold", 75)
    storage.set_setting("scrape_params", {"sites": ["indeed"], "location": "Remote"})
    assert storage.get_setting("score_threshold") == 75
    assert storage.get_setting("scrape_params")["location"] == "Remote"
    assert storage.get_setting("missing", "fallback") == "fallback"


def test_run_lifecycle(temp_db):
    run_id = storage.create_run("cron")
    run = storage.get_run(run_id)
    assert run["status"] == "running"
    assert run["trigger"] == "cron"
    storage.finish_run(run_id, "completed", jobs_scraped=5, new_jobs=2, scored=2, alerts_sent=1)
    run = storage.get_run(run_id)
    assert run["status"] == "completed"
    assert run["jobs_scraped"] == 5
    assert len(storage.list_runs()) == 1


def test_skills_stored_as_json(temp_db):
    storage.upsert_job(_job(matched_skills=["python", "sql"], missing_skills=["go"]))
    job = storage.list_jobs()[0]
    assert job["matched_skills"] == ["python", "sql"]
    assert job["missing_skills"] == ["go"]
