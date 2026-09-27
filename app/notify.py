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


TELEGRAM_MESSAGE_LIMIT = 4000  # hard cap 4096; leave headroom


def format_alert_chunks(
    candidates: List[Dict[str, Any]],
) -> List[str]:
    """Render the alert as one or more messages (None-safe empty list).

    EVERY above-threshold job is included — no top-N cap. Telegram's 4096-char
    limit is handled by starting a new message when one fills up.
    """
    if not candidates:
        return []
    messages: List[str] = []
    lines: List[str] = []

    def flush():
        if lines:
            messages.append("\n".join(lines).strip())
            lines.clear()

    header = f"🎯 {len(candidates)} new job match(es) above threshold:"
    lines.append(header)

    for job in candidates:
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
        # A single job entry must never overflow a message on its own.
        if len(line) > TELEGRAM_MESSAGE_LIMIT:
            line = line[: TELEGRAM_MESSAGE_LIMIT - 20] + "\n  …"
        if sum(len(l) for l in lines) + len(line) > TELEGRAM_MESSAGE_LIMIT:
            flush()
            lines.append(header)
        lines.append(line)

    flush()
    return messages


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
) -> int:
    """Alert about EVERY unsent above-threshold match; return how many were sent.

    No top-N cap: all candidates go out, chunked across as many messages as
    Telegram's size limit requires. Only jobs in delivered messages are marked
    ``notified``. When Telegram is unconfigured the selection is still computed
    (and logged) but nothing is marked, so a later configured run alerts them.
    """
    from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    effective_threshold = threshold if threshold is not None else 70
    token = bot_token if bot_token is not None else TELEGRAM_BOT_TOKEN
    chat = chat_id if chat_id is not None else TELEGRAM_CHAT_ID

    candidates = _select_candidates(effective_threshold)
    if not candidates:
        return 0

    messages = format_alert_chunks(candidates)
    if not messages:
        return 0

    if not token or not chat:
        logger.warning(
            "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID); "
            "%d above-threshold job(s) pending notification.",
            len(candidates),
        )
        return 0

    sent_keys: List[str] = []
    for index, message in enumerate(messages):
        if not send_telegram(message, token, chat):
            logger.error(
                "Telegram message %d/%d failed; %d job(s) remain pending "
                "and will retry next run.",
                index + 1, len(messages), len(candidates) - len(sent_keys),
            )
            break
        # Mark exactly the jobs that went out in this delivered chunk.
        chunk_keys = [job["job_key"] for job in candidates if job["job_key"] not in sent_keys]
        chunk_keys = chunk_keys[: _jobs_in_chunk(candidates, sent_keys, message)]
        sent_keys.extend(chunk_keys)

    if sent_keys:
        storage.mark_notified(sorted(set(sent_keys)))
    return len(sent_keys)


def _jobs_in_chunk(candidates, already_sent, message) -> int:
    """How many pending candidates the delivered message contained."""
    # Chunks are built in candidate order, so count the entries in the
    # delivered text ("• " bullets) beyond what earlier chunks covered.
    return message.count("\n• ")
