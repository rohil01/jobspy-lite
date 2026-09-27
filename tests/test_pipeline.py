"""Pipeline tests with fake AI agent + scraper (no network)."""

from datetime import datetime, timedelta, timezone

from app import storage
from app.pipeline import PipelineContext, _needs_scoring, run_pipeline


class FakeAgent:
    """Deterministic stand-in for AIJobAgent."""

    def __init__(self, score=85):
        self.score = score

    def _estimate_required_years(self, job):
        return {"min": 1, "max": 2}

    def assess_suitability(self, job, resume_text):
        return {
            "score": self.score,
            "final_score": self.score,
            "verdict": "strong",
            "matched_skills": ["python"],
            "missing_skills": ["kafka"],
            "reasoning": "solid fit",
        }


def _seed_context(resume_hash="hash1"):
    storage.set_setting(
        "resume", {"text": "my resume", "name": "r.docx", "hash": resume_hash}
    )
    return PipelineContext()


def test_needs_scoring_rules(temp_db):
    context = _seed_context()
    assert _needs_scoring(None, context) is True  # brand new

    scored_row = {
        "score": 80,
        "required_years_min": 1,
        "scored_with_resume": "hash1",
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    assert _needs_scoring(scored_row, context) is False  # fresh + same resume

    other_resume = dict(scored_row, scored_with_resume="hash2")
    assert _needs_scoring(other_resume, context) is True  # resume changed

    stale = dict(
        scored_row,
        scored_at=(datetime.now(timezone.utc) - timedelta(hours=73)).isoformat(),
    )
    assert _needs_scoring(stale, context) is True  # older than 72h

    unscored = {"score": None, "required_years_min": None, "scored_at": None}
    assert _needs_scoring(unscored, context) is True


def test_needs_scoring_disabled_rescore_window(temp_db, monkeypatch):
    """RESCORE_AFTER_HOURS=0 means: never re-score stale jobs (a new resume
    or an unscored row still triggers scoring)."""
    import app.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "RESCORE_AFTER_HOURS", 0)
    context = _seed_context()
    stale = {
        "score": 80,
        "required_years_min": 1,
        "scored_with_resume": "hash1",
        "scored_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
    }
    assert _needs_scoring(stale, context) is False
    assert _needs_scoring(dict(stale, scored_with_resume="hash2"), context) is True
    assert _needs_scoring({"score": None, "required_years_min": None, "scored_at": None}, context) is True


def test_needs_scoring_force(temp_db):
    context = _seed_context()
    context.force_rescore = True
    fresh_row = {
        "score": 80,
        "required_years_min": 1,
        "scored_with_resume": "hash1",
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    assert _needs_scoring(fresh_row, context) is True


def test_concurrent_run_is_skipped(temp_db, monkeypatch):
    """A second run_pipeline while one holds the lock returns skipped without
    scraping — cron and manual runs must never overlap."""
    import threading

    import app.pipeline as pipeline_module

    _seed_context()
    started = threading.Event()
    release = threading.Event()

    def slow_execute(trigger="manual", force_rescore=False, progress_callback=None):
        started.set()
        release.wait(timeout=5)
        return {"status": "completed", "scored": 0}

    monkeypatch.setattr(pipeline_module, "_execute_pipeline", slow_execute)

    results = {}

    def first():
        results["first"] = run_pipeline(trigger="cron")

    t = threading.Thread(target=first)
    t.start()
    assert started.wait(timeout=5)  # first run holds the lock now

    second = run_pipeline(trigger="manual")
    release.set()
    t.join(timeout=5)

    assert second["status"] == "skipped"
    assert "already in progress" in second["error"]
    assert results["first"]["status"] == "completed"


def test_failed_scoring_is_recorded_and_retried(temp_db, monkeypatch):
    """AI failures must be tracked (attempts + error) and retried next run —
    never written as fake verdicts that stick forever."""
    _seed_context()

    attempts = {"n": 0}

    class FlakyAgent:
        def _estimate_required_years(self, job):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("NVIDIA down")
            return {"min": 1, "max": 2}

        def assess_suitability(self, job, resume_text):
            return {
                "score": 77, "final_score": 77, "verdict": "good",
                "matched_skills": ["python"], "missing_skills": [],
                "reasoning": "ok",
            }

    class OneJobScraper:
        def __init__(self, config):
            pass

        def scrape(self):
            return [{
                "title": "Retry Me", "company": "Acme", "site": "linkedin",
                "job_url": "https://example.com/retry", "description": "d",
            }]

    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "JobScraper", OneJobScraper)
    monkeypatch.setattr(pipeline_module, "AIJobAgent", lambda config: FlakyAgent())
    monkeypatch.setattr(
        pipeline_module.notify, "notify_above_threshold", lambda *a, **k: 0
    )

    # Run 1: agent fails -> run completes, job recorded as failed, no fake verdict
    s1 = run_pipeline(trigger="manual")
    assert s1["status"] == "completed"
    job = storage.get_job("https://example.com/retry")
    assert job["score_attempts"] == 1
    assert "NVIDIA down" in job["score_error"]
    assert job["verdict"] is None and job["score"] is None

    # Run 2: agent healthy -> job scores, bookkeeping cleared
    s2 = run_pipeline(trigger="manual")
    assert s2["status"] == "completed" and s2["scored"] == 1
    job = storage.get_job("https://example.com/retry")
    assert job["score"] == 77
    assert job["score_attempts"] == 0 and job["score_error"] is None


def test_stale_running_runs_are_reaped(temp_db):
    """Runs stuck in 'running' (deploy/crash mid-run) get closed out."""
    from datetime import datetime, timedelta, timezone

    old = storage.create_run("manual")
    # Backdate the row beyond the reap window.
    storage.query("UPDATE runs SET started_at = ?", (
        (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    ))
    fresh = storage.create_run("manual")

    reaped = storage.reap_stale_runs(max_age_minutes=30)
    assert reaped == 1
    assert storage.get_run(old)["status"] == "failed"
    assert "interrupted" in storage.get_run(old)["error"]
    assert storage.get_run(fresh)["status"] == "running"


def test_run_pipeline_no_resume_fails_cleanly(temp_db):
    summary = run_pipeline(trigger="manual")
    assert summary["status"] == "failed"
    assert "resume" in summary["error"].lower()
    runs = storage.list_runs()
    assert runs[0]["status"] == "failed"


def test_run_pipeline_end_to_end_with_fakes(temp_db, monkeypatch):
    _seed_context()

    # Fake scraper: two postings, one already in the DB with user-accepted state.
    class FakeScraper:
        def __init__(self, config):
            pass

        def scrape(self):
            return [
                {
                    "title": "AI Engineer",
                    "company": "Acme",
                    "location": "Bengaluru",
                    "site": "linkedin",
                    "job_url": "https://example.com/1",
                    "description": "Build AI things",
                },
                {
                    "title": "Data Engineer",
                    "company": "Globex",
                    "location": "Remote",
                    "site": "indeed",
                    "job_url": "https://example.com/2",
                    "description": "Move data",
                },
            ]

    import app.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "JobScraper", FakeScraper)
    monkeypatch.setattr(pipeline_module, "AIJobAgent", lambda config: FakeAgent())

    # Pre-store posting 1 as accepted so we can prove upsert preserves it.
    key1 = storage.upsert_job({"job_url": "https://example.com/1", "title": "x"})
    storage.set_job_status(key1, "accepted")

    # Pre-mark posting 2 as notified so it must NOT be alerted again.
    key2 = storage.upsert_job({"job_url": "https://example.com/2", "title": "y"})
    storage.mark_notified([key2])

    sent = {}

    def fake_notify(threshold, **kwargs):
        sent["threshold"] = threshold
        return 1  # pretend one alert went out

    monkeypatch.setattr(pipeline_module.notify, "notify_above_threshold", fake_notify)

    summary = run_pipeline(trigger="cron")

    assert summary["status"] == "completed"
    assert summary["jobs_scraped"] == 2
    assert summary["new_jobs"] == 0  # both pre-existed
    assert summary["scored"] == 2
    assert summary["alerts_sent"] == 1
    assert sent["threshold"] == 70  # default threshold

    job1 = storage.get_job(key1)
    assert job1["status"] == "accepted"  # user state preserved through re-score
    assert job1["score"] == 85
    assert job1["scored_with_resume"] == "hash1"

    run_row = storage.get_run(summary["run_id"])
    assert run_row["status"] == "completed"
    assert run_row["scored"] == 2
