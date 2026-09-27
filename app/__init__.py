"""JobSpy Lite — scraper + AI agent + scheduler + tracking UI.

A slimmed-down, standalone version of JobSpy: scrape job postings, screen them
against a stored resume with two AI agents (required-experience estimate and
resume-suitability score), persist everything to SQLite (with Excel export),
run on a cron schedule, and notify above-threshold matches via Telegram.
"""

__version__ = "0.1.0"
