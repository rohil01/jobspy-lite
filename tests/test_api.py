"""API tests via FastAPI TestClient on a temporary database."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(temp_db, monkeypatch):
    # Keep the notify test-hook out of the way: no real Telegram config.
    monkeypatch.setattr("app.api.notify.notify_above_threshold", lambda *a, **k: 0)
    from app.api import app

    return TestClient(app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "ai_model" in body
    assert body["db_ready"] is True


def test_resume_upload_and_get(client, tmp_path):
    # Build a minimal real .docx so extract_text succeeds.
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_paragraph("John Doe — Python developer")
    buffer = BytesIO()
    document.save(buffer)

    response = client.post(
        "/resume",
        files={"resume": ("resume.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 200
    info = response.json()
    assert info["name"] == "resume.docx"
    assert info["hash"]

    fetched = client.get("/resume").json()
    assert fetched["name"] == "resume.docx"
    assert fetched["chars"] > 0


def test_resume_requires_docx(client):
    response = client.post("/resume", files={"resume": ("x.txt", b"plain text", "text/plain")})
    assert response.status_code == 400


def test_jobs_status_flow(client):
    from app import storage

    key = storage.upsert_job({"job_url": "https://x/1", "title": "Role", "score": 90})
    response = client.post(f"/jobs/{key}/status", json={"new_status": "accepted"})
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert storage.get_job(key)["status"] == "accepted"

    bad = client.post(f"/jobs/{key}/status", json={"new_status": "banana"})
    assert bad.status_code == 400 or bad.status_code == 500

    missing = client.post("/jobs/unknown-key/status", json={"new_status": "new"})
    assert missing.status_code == 404


def test_jobs_listing_and_stats(client):
    from app import storage

    k1 = storage.upsert_job({"job_url": "https://x/1", "title": "A", "score": 90, "company": "C1"})
    k2 = storage.upsert_job({"job_url": "https://x/2", "title": "B", "score": 40, "company": "C2"})
    storage.set_job_status(k1, "accepted")

    listing = client.get("/jobs?status=accepted").json()
    assert listing["count"] == 1
    assert listing["jobs"][0]["job_key"] == k1

    stats = client.get("/stats").json()
    assert stats["total"] == 2
    assert stats["accepted"] == 1
    assert stats["new"] == 1


def test_scheduler_config_validation(client):
    # Invalid mode rejected.
    bad = client.post("/scheduler/config", json={"mode": "weekly"})
    assert bad.status_code == 400

    # Valid cron accepted and persisted.
    ok = client.post("/scheduler/config", json={"mode": "cron", "cron_expression": "0 */2 * * *"})
    assert ok.status_code == 200
    assert ok.json()["config"]["cron_expression"] == "0 */2 * * *"

    # Invalid cron expression rejected with detail.
    bad_cron = client.post("/scheduler/config", json={"mode": "cron", "cron_expression": "not a cron"})
    assert bad_cron.status_code == 400

    status = client.get("/scheduler").json()
    assert status["enabled"] is False  # config saved but scheduler not started


def test_scheduler_toggle_starts_and_stops(client):
    on = client.post("/scheduler/toggle?enabled=true").json()
    assert on["running"] is True
    assert on["enabled"] is True
    assert on["next_run_at"]

    off = client.post("/scheduler/toggle?enabled=false").json()
    assert off["running"] is False
    assert off["enabled"] is False


def test_settings_roundtrip(client):
    updated = client.post(
        "/settings",
        json={"score_threshold": 65, "experience_min_years": 1, "experience_max_years": 3},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["score_threshold"] == 65
    assert body["experience_min_years"] == 1
    assert body["experience_max_years"] == 3


def test_agent_params_roundtrip_and_sanitization(client):
    updated = client.post(
        "/settings",
        json={"agent_params": {
            "ai_model": "mymodel/v2",
            "ai_base_url": "https://example.invalid/v1",
            "ai_rate_limit_per_min": 15,
            "max_workers": 6,
            "api_key": "should-not-persist",
        }},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["agent_params"]["ai_model"] == "mymodel/v2"
    assert body["agent_params"]["ai_base_url"] == "https://example.invalid/v1"
    assert body["agent_params"]["ai_rate_limit_per_min"] == 15
    assert body["max_workers"] == 6
    assert "api_key" not in body["agent_params"]

    from app import storage
    assert "api_key" not in (storage.get_setting("agent_params") or {})

    # Empty model is dropped (falls back to env default); junk rate limit -> 30.
    fallback = client.post(
        "/settings",
        json={"agent_params": {"ai_model": "  ", "ai_rate_limit_per_min": "bogus"}},
    )
    assert fallback.status_code == 200
    params = fallback.json()["agent_params"]
    assert params["ai_model"] != "  "
    assert params["ai_rate_limit_per_min"] == 30


def test_scrape_params_roundtrip(client):
    updated = client.post(
        "/settings",
        json={"scrape_params": {"search_terms": ["ML Engineer"], "hours_old": 6, "location": "Remote"}},
    )
    assert updated.status_code == 200
    params = updated.json()["scrape_params"]
    assert params["search_terms"] == ["ML Engineer"]
    assert params["hours_old"] == 6
    assert params["location"] == "Remote"


def test_export_xlsx(client):
    from app import storage

    storage.upsert_job({"job_url": "https://x/1", "title": "A", "score": 90})
    response = client.get("/export.xlsx")
    assert response.status_code == 200
    assert response.content.startswith(b"PK")  # zip magic = valid xlsx


def test_runs_listed(client):
    from app import storage

    run_id = storage.create_run("manual")
    storage.finish_run(run_id, "completed", jobs_scraped=3)
    runs = client.get("/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["trigger"] == "manual"
