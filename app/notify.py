"""Telegram notifications for above-threshold job matches.

After every pipeline run (cron or manual), jobs meeting ALL of:
  - ``score >= threshold``
  - ``experience_match``
  - ``status != 'rejected'``
  - ``notified = 0``
are batched into ONE Telegram message (top N by score) via the Bot API
``sendMessage``. Matched jobs are then flagged ``notified = 1`` so nothing is
ever sent twice. Unset token/chat id = graceful no-op (a logged warning), so
local runs without Telegram never crash the pipeline.
"""

import logging
from typing import Any, Dict, List, Optional

import requests

from . import storage

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


def _select_candidates(threshold: int) -> List[Dict[str, Any]]:
    """Jobs that passed the gate and have never been alerted, best first."""
    rows = storage.query(
        """
        SELECT * FROM jobs
         WHERE score IS NOT NULL
           AND score >= ?
           AND experience_match = 1
           AND status != 'rejected'
           AND notified = 0
         ORDER BY score DESC
        """,
        (threshold,),
    )
    return [dict(row) for row in rows]


def format_alert(candidates: List[Dict[str, Any]], top_n: int) -> Optional[str]:
    """Render the batched alert message (None when nothing to send).

    Telegram captions/messages cap at 4096 chars; the formatter truncates.
    """
    if not candidates:
        return None
    lines = [f"🎯 {len(candidates)} new job match(es) above threshold:"]
    for job in candidates[:top_n]:
        skills = ", ".join((job.get("matched_skills") or [])[:3])
        line = (
            f"\n• {job.get('title') or 'Untitled'} @ {job.get('company') or '?'}"
            f" — score {job.get('score')}"
        )
        if job.get("verdict"):
            line += f" ({job['verdict']})"
        if skills:
            line += f"\n  ✓ {skills}"
        if job.get("job_url"):
            line += f"\n  {job['job_url']}"
        lines.append(line)
    message = "\n".join(lines)
    if len(message) > 4000:
        message = message[:4000] + "\n…"
    return message


def send_telegram(message: str, bot_token: str, chat_id: str, timeout: float = 10.0) -> bool:
    """POST one message to the Bot API. Returns True on 'ok' response."""
    try:
        response = requests.post(
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=timeout,
        )
        payload = response.json() if response.content else {}
        if not response.ok or not payload.get("ok"):
            logger.error(
                "Telegram send failed: status=%s body=%s", response.status_code, payload
            )
            return False
        return True
    except requests.RequestException as exc:
        logger.error("Telegram send error: %s", exc)
        return False


def notify_above_threshold(
    threshold: Optional[int] = None,
    *,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    top_n: Optional[int] = None,
) -> int:
    """Alert about unsent above-threshold matches; return how many were sent.

    Only jobs actually included in a delivered message are marked ``notified``.
    When Telegram is unconfigured the selection is still computed (and logged)
    but nothing is marked, so a later configured run alerts everything pending.
    """
    from .config import NOTIFY_TOP_N, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    effective_threshold = threshold if threshold is not None else 70
    effective_top_n = top_n if top_n is not None else NOTIFY_TOP_N
    token = bot_token if bot_token is not None else TELEGRAM_BOT_TOKEN
    chat = chat_id if chat_id is not None else TELEGRAM_CHAT_ID

    candidates = _select_candidates(effective_threshold)
    if not candidates:
        return 0

    message = format_alert(candidates, effective_top_n)
    if message is None:
        return 0

    if not token or not chat:
        logger.warning(
            "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID); "
            "%d above-threshold job(s) pending notification.",
            len(candidates),
        )
        return 0

    if not send_telegram(message, token, chat):
        return 0

    selected = {job["job_key"] for job in candidates[:effective_top_n]}
    storage.mark_notified(sorted(selected))
    return len(selected)
