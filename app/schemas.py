"""Pydantic models for the JobSpy Lite API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    ai_model: str
    scheduler_running: bool
    resume_uploaded: bool
    telegram_configured: bool
    db_ready: bool


class ResumeInfo(BaseModel):
    name: Optional[str] = None
    chars: Optional[int] = None
    hash: Optional[str] = None
    uploaded_at: Optional[str] = None


class JobListResponse(BaseModel):
    count: int
    total: int
    jobs: List[Dict[str, Any]]


class StatsResponse(BaseModel):
    total: int
    new: int
    accepted: int
    rejected: int
    avg_score: Optional[float] = None


class RunLatest(BaseModel):
    running: bool
    progress: Optional[str] = None
    percent: Optional[float] = None
    summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    last_run: Optional[Dict[str, Any]] = None


class SchedulerStatus(BaseModel):
    running: bool
    enabled: bool
    config: Dict[str, Any]
    next_run_at: Optional[str] = None
    last_run: Optional[Dict[str, Any]] = None


class SettingsIn(BaseModel):
    scrape_params: Optional[Dict[str, Any]] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    score_threshold: Optional[int] = None


class JobStatusIn(BaseModel):
    new_status: str
