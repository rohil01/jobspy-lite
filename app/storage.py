"""SQLite persistence layer for JobSpy Lite.

Three tables, all created idempotently:

- ``jobs``     — one row per unique posting (keyed by the stable job identity).
                 Screening annotations are upserted; user state (``status``,
                 ``notified``) is never clobbered by re-scrapes.
- ``runs``     — one row per pipeline execution (cron or manual), for history
                 and for verifying the scheduler actually fired.
- ``settings`` — JSON-key/value store for runtime-editable configuration
                 (threshold, experience window, scrape params, cron config,
                 the stored resume).

WAL mode is enabled for safe concurrent reads while the pipeline writes.
"""

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DB_PATH
from .util import make_json_safe

_conn_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_key            TEXT PRIMARY KEY,
    site               TEXT,
    title              TEXT,
    company            TEXT,
    location           TEXT,
    description        TEXT,
    job_url            TEXT,
    date_posted        TEXT,
    job_type           TEXT,
    is_remote          INTEGER,
    min_amount         REAL,
    max_amount         REAL,
    currency           TEXT,
    interval           TEXT,
    required_years_min INTEGER,
    required_years_max INTEGER,
    experience_match   INTEGER,
    score              REAL,
    verdict            TEXT,
    matched_skills     TEXT,
    missing_skills     TEXT,
    reasoning          TEXT,
    status             TEXT NOT NULL DEFAULT 'new',
    notified           INTEGER NOT NULL DEFAULT 0,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    scored_at          TEXT,
    scored_with_resume TEXT,
    score_attempts     INTEGER NOT NULL DEFAULT 0,
    score_error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_seen ON jobs(first_seen_at);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL UNIQUE,
    trigger       TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    jobs_scraped  INTEGER,
    new_jobs      INTEGER,
    scored        INTEGER,
    alerts_sent   INTEGER,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    """Open (once) and return the process-wide SQLite connection."""
    global _conn
    with _conn_lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _conn.executescript(_SCHEMA)
            _migrate()
            _conn.commit()
        return _conn


def _migrate() -> None:
    """Lightweight column additions for pre-existing databases."""
    cols = {row["name"] for row in _conn.execute("PRAGMA table_info(jobs)")}
    for name, ddl in (
        ("score_attempts", "ALTER TABLE jobs ADD COLUMN score_attempts INTEGER NOT NULL DEFAULT 0"),
        ("score_error", "ALTER TABLE jobs ADD COLUMN score_error TEXT"),
    ):
        if name not in cols:
            _conn.execute(ddl)


@contextmanager
def transaction():
    """Yield a connection with an open transaction; commit or roll back."""
    conn = connect()
    with _conn_lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Run a read-only query, returning rows as dicts."""
    conn = connect()
    with _conn_lock:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def query_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    rows = query(sql, params)
    return rows[0] if rows else None


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(make_json_safe(value), ensure_ascii=False)


def _job_row_values(job_key_value: str, annotated: Dict[str, Any], now: str,
                    existing: Optional[Dict[str, Any]]) -> tuple:
    """Build the column tuple for an upsert of one annotated job."""
    required = annotated.get("required_years") or {}
    required_min = required.get("min") if isinstance(required, dict) else None
    required_max = required.get("max") if isinstance(required, dict) else None
    score = annotated.get("final_score")
    if score is None:
        score = annotated.get("score")
    scored = bool(
        annotated.get("score") is not None or annotated.get("required_years") is not None
    )
    return (
        job_key_value,
        annotated.get("site"),
        annotated.get("title"),
        annotated.get("company"),
        annotated.get("location"),
        annotated.get("description"),
        annotated.get("job_url") or annotated.get("url"),
        str(annotated.get("date_posted")) if annotated.get("date_posted") is not None else None,
        annotated.get("job_type") or annotated.get("employment_type"),
        1 if annotated.get("is_remote") else 0,
        annotated.get("min_amount"),
        annotated.get("max_amount"),
        annotated.get("currency"),
        annotated.get("interval"),
        required_min,
        required_max,
        1 if annotated.get("experience_match") else 0,
        score,
        annotated.get("verdict"),
        _json_or_none(annotated.get("matched_skills")),
        _json_or_none(annotated.get("missing_skills")),
        annotated.get("reasoning"),
        # User state: on insert honor what the caller supplied (tests seed
        # status/notified this way; real scrapes never set them); on update
        # preserve the stored values so re-scrapes never clobber a decision.
        (existing or {}).get("status") or annotated.get("status") or "new",
        (existing or {}).get("notified") if existing else (1 if annotated.get("notified") else 0),
        (existing or {}).get("first_seen_at") or now,
        now,  # last_seen_at always refreshed
        now if scored else (existing or {}).get("scored_at"),
        annotated.get("scored_with_resume"),
    )


_UPSERT_SQL = """
INSERT INTO jobs (
    job_key, site, title, company, location, description, job_url, date_posted,
    job_type, is_remote, min_amount, max_amount, currency, interval,
    required_years_min, required_years_max, experience_match, score, verdict,
    matched_skills, missing_skills, reasoning, status, notified,
    first_seen_at, last_seen_at, scored_at, scored_with_resume
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(job_key) DO UPDATE SET
    site=excluded.site, title=excluded.title, company=excluded.company,
    location=excluded.location, description=excluded.description,
    job_url=excluded.job_url, date_posted=excluded.date_posted,
    job_type=excluded.job_type, is_remote=excluded.is_remote,
    min_amount=excluded.min_amount, max_amount=excluded.max_amount,
    currency=excluded.currency, interval=excluded.interval,
    required_years_min=excluded.required_years_min,
    required_years_max=excluded.required_years_max,
    experience_match=excluded.experience_match,
    score=excluded.score, verdict=excluded.verdict,
    matched_skills=excluded.matched_skills, missing_skills=excluded.missing_skills,
    reasoning=excluded.reasoning, last_seen_at=excluded.last_seen_at,
    scored_at=excluded.scored_at, scored_with_resume=excluded.scored_with_resume,
    status=excluded.status, notified=excluded.notified
"""

# Same upsert for RAW scrapes (no AI annotation yet): refresh listing fields
# and user state but KEEP the stored AI results, so re-scraping a job never
# wipes its score or tricks the pipeline into re-running the agent on it.
_UPSERT_SQL_RAW = """
INSERT INTO jobs (
    job_key, site, title, company, location, description, job_url, date_posted,
    job_type, is_remote, min_amount, max_amount, currency, interval,
    required_years_min, required_years_max, experience_match, score, verdict,
    matched_skills, missing_skills, reasoning, status, notified,
    first_seen_at, last_seen_at, scored_at, scored_with_resume
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(job_key) DO UPDATE SET
    site=excluded.site, title=excluded.title, company=excluded.company,
    location=excluded.location, description=excluded.description,
    job_url=excluded.job_url, date_posted=excluded.date_posted,
    job_type=excluded.job_type, is_remote=excluded.is_remote,
    min_amount=excluded.min_amount, max_amount=excluded.max_amount,
    currency=excluded.currency, interval=excluded.interval,
    last_seen_at=excluded.last_seen_at,
    status=excluded.status, notified=excluded.notified
"""


def upsert_job(annotated: Dict[str, Any], job_key_value: Optional[str] = None) -> str:
    """Insert or update one job row. Returns the job key.

    User state (``status``/``notified``) is preserved when the row already
    exists — re-scrapes and re-scores never overwrite an accept/reject.
    When the payload carries AI results (score/required_years/verdict) they
    replace the stored ones; a RAW scrape (no AI fields) keeps them, so a
    job scored once is never silently reset to unscored.
    """
    from .util import job_key as compute_key

    key = job_key_value or compute_key(annotated)
    now = _utc_now()
    has_ai = (
        annotated.get("required_years") is not None
        or annotated.get("score") is not None
        or annotated.get("experience_match") is not None
        or bool(annotated.get("verdict"))
    )
    with transaction() as conn:
        existing = conn.execute(
            "SELECT status, notified, first_seen_at, scored_at FROM jobs WHERE job_key = ?",
            (key,),
        ).fetchone()
        existing_dict = dict(existing) if existing else None
        values = _job_row_values(key, annotated, now, existing_dict)
        conn.execute(_UPSERT_SQL if has_ai else _UPSERT_SQL_RAW, values)
    return key


def get_job(job_key_value: str) -> Optional[Dict[str, Any]]:
    """One job row (with parsed skill lists), or None."""
    row = query_one("SELECT * FROM jobs WHERE job_key = ?", (job_key_value,))
    return _decode_job(row) if row else None


def _decode_job(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    job = dict(row)
    for column in ("matched_skills", "missing_skills"):
        try:
            job[column] = json.loads(job[column]) if job.get(column) else []
        except (TypeError, json.JSONDecodeError):
            job[column] = []
    return job


def list_jobs(
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    order: str = "score",
) -> List[Dict[str, Any]]:
    """Jobs as dicts, newest-first within equal scores, with parsed skills."""
    allowed_orders = {"score": "score DESC", "recent": "last_seen_at DESC", "title": "title ASC"}
    order_clause = allowed_orders.get(order, allowed_orders["score"])
    sql = "SELECT * FROM jobs"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += f" ORDER BY {order_clause}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return [job for job in (_decode_job(row) for row in query(sql, tuple(params))) if job]


def counts_by_status() -> Dict[str, int]:
    """Job counts keyed by status, plus total and average score."""
    rows = query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    counts = {row["status"]: row["n"] for row in rows}
    total = sum(counts.values())
    avg = query_one("SELECT AVG(score) AS avg_score FROM jobs WHERE score IS NOT NULL")
    counts["total"] = total
    counts["avg_score"] = round(avg["avg_score"], 1) if avg and avg["avg_score"] is not None else None
    return counts


def set_job_status(
    job_key_value: str, status: str, *, only_if_status: Optional[str] = None
) -> bool:
    """Set a job's user status (new/accepted/rejected). Returns True if it exists.

    Pass ``only_if_status`` for a compare-and-set update: the status changes
    only when the stored status still equals that value (used by the
    auto-reject rule so it never clobbers a user's accept/reject).
    """
    if status not in ("new", "accepted", "rejected"):
        raise ValueError(f"Invalid status '{status}'.")
    if only_if_status is not None and only_if_status not in ("new", "accepted", "rejected"):
        raise ValueError(f"Invalid guard status '{only_if_status}'.")
    with transaction() as conn:
        sql = "UPDATE jobs SET status = ? WHERE job_key = ?"
        params: list = [status, job_key_value]
        if only_if_status is not None:
            sql += " AND status = ?"
            params.append(only_if_status)
        cursor = conn.execute(sql, tuple(params))
        return cursor.rowcount > 0


def mark_notified(job_keys: List[str]) -> None:
    """Flag jobs as notified so they are never re-alerted."""
    if not job_keys:
        return
    with transaction() as conn:
        conn.executemany(
            "UPDATE jobs SET notified = 1 WHERE job_key = ?",
            [(key,) for key in job_keys],
        )


def create_run(trigger: str) -> str:
    """Register a new pipeline run and return its run_id."""
    run_id = uuid.uuid4().hex
    with transaction() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, trigger, status, started_at) VALUES (?,?,?,?)",
            (run_id, trigger, "running", _utc_now()),
        )
    return run_id


def finish_run(
    run_id: str,
    status: str,
    *,
    jobs_scraped: Optional[int] = None,
    new_jobs: Optional[int] = None,
    scored: Optional[int] = None,
    alerts_sent: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Complete a run row with its outcome counters."""
    with transaction() as conn:
        conn.execute(
            """
            UPDATE runs
               SET status = ?, finished_at = ?, jobs_scraped = ?, new_jobs = ?,
                   scored = ?, alerts_sent = ?, error = ?
             WHERE run_id = ?
            """,
            (status, _utc_now(), jobs_scraped, new_jobs, scored, alerts_sent, error, run_id),
        )


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Recent runs, newest first."""
    return query(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    )


def reap_stale_runs(max_age_minutes: Optional[int] = 30) -> int:
    """Close out runs stuck in 'running' with no heartbeat.

    Covers hard crashes and container restarts mid-run (deploys kill the
    thread; the DB row used to stay 'running' forever). Pass
    ``max_age_minutes=None`` to reap ALL running rows — correct at process
    startup, where a 'running' row is by definition orphaned (single
    process, max_instances=1). Returns rows closed.
    """
    where = "WHERE status = 'running'"
    params: list = []
    if max_age_minutes is not None:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        ).isoformat()
        where += " AND started_at < ?"
        params.append(cutoff)
    with transaction() as conn:
        cur = conn.execute(
            f"""
            UPDATE runs
               SET status = 'failed',
                   finished_at = ?,
                   error = COALESCE(error, 'run interrupted (process restart/deploy)')
             {where}
            """,
            [_utc_now(), *params],
        )
    return cur.rowcount


MAX_SCORE_ATTEMPTS = 3


def record_score_failure(job_key: str, error: str) -> None:
    """Bump the attempt counter and store the last error for one job."""
    with transaction() as conn:
        conn.execute(
            """
            UPDATE jobs
               SET score_attempts = score_attempts + 1,
                   score_error = ?
             WHERE job_key = ?
            """,
            (error[:500], job_key),
        )


def clear_score_failure(job_key: str) -> None:
    """Reset the failure bookkeeping after a successful score."""
    with transaction() as conn:
        conn.execute(
            "UPDATE jobs SET score_attempts = 0, score_error = NULL WHERE job_key = ?",
            (job_key,),
        )


def needs_score_retry(row: Dict[str, Any]) -> bool:
    """A row failed AI scoring before and still has attempts left."""
    attempts = row.get("score_attempts") or 0
    return (
        row.get("score") is None
        and bool(row.get("score_error"))
        and attempts < MAX_SCORE_ATTEMPTS
    )


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    return query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))


# --------------------------------------------------------------------------- #
# Settings (JSON key/value)
# --------------------------------------------------------------------------- #
def get_setting(key: str, default: Any = None) -> Any:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return default


def set_setting(key: str, value: Any) -> None:
    encoded = json.dumps(make_json_safe(value), ensure_ascii=False)
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, encoded),
        )


def all_settings() -> Dict[str, Any]:
    return {row["key"]: json.loads(row["value"]) for row in query("SELECT * FROM settings")}


def close() -> None:
    """Close the shared connection (used by tests)."""
    global _conn
    with _conn_lock:
        if _conn is not None:
            _conn.close()
            _conn = None
