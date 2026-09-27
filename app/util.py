"""Small shared helpers used by the scraper, pipeline, and storage layers."""

import hashlib
import logging
import time
from datetime import date, datetime, time as time_of_day
from decimal import Decimal
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def make_json_safe(value: Any) -> Any:
    """Convert non-JSON-native Python values (dates, Decimals, NaN) safely."""
    if isinstance(value, (datetime, date, time_of_day)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    return value


def job_key(job: Dict[str, Any]) -> str:
    """Stable identity for a posting.

    Prefers ``job_url``; falls back to a hash of title/company/location/date so
    postings without a URL still collapse when they are genuinely the same.
    Mirrors the identity rule used by the original JobSpy project.
    """
    url = job.get("job_url") or job.get("url")
    if url:
        return str(url)
    fallback = (
        f"{job.get('title', '')}|{job.get('company', '')}|"
        f"{job.get('location', '')}|{job.get('date_posted', '')}"
    )
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()


def deduplicate_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop exact-duplicate postings (same identity key), keeping first seen."""
    seen = set()
    unique: List[Dict[str, Any]] = []
    for job in jobs:
        key = job_key(job)
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def cooldown_sleep(minutes: float, log: logging.Logger) -> None:
    """Pause between search-term scrapes; fractional minutes allowed."""
    seconds = max(0.0, float(minutes) * 60.0)
    if seconds <= 0:
        return
    log.info("Cooling down for %dm %ds…", int(seconds // 60), int(seconds % 60))
    time.sleep(seconds)
