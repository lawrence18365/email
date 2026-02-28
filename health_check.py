#!/usr/bin/env python3
"""
Pre-flight health checks for the email outreach system.

Runs at the START of each cron cycle. If a critical dependency is broken
(API key, SMTP, database), sends a Telegram alert and aborts the run
so we don't silently fail for hours.

Usage:
  python health_check.py          # Run all checks, exit 1 on critical failure
  python health_check.py --warn   # Run all checks, never abort (warnings only)
"""

import os
import sys
import logging

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_openrouter_api_key():
    """Verify OPENROUTER_API_KEY is set and the API responds."""
    key = os.getenv('OPENROUTER_API_KEY', '')
    if not key:
        return False, "OPENROUTER_API_KEY is not set — AI auto-replies will fail silently"
    if len(key) < 20:
        return False, f"OPENROUTER_API_KEY looks invalid (length={len(key)})"
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10
        )
        if resp.status_code == 401:
            return False, "OPENROUTER_API_KEY is invalid (401 Unauthorized)"
        if resp.status_code != 200:
            return False, f"OpenRouter API returned {resp.status_code}"
        return True, "OK"
    except Exception as e:
        return False, f"OpenRouter API unreachable: {e}"


def check_database():
    """Verify database is accessible and has expected tables."""
    from models import db, Lead, Campaign
    try:
        lead_count = Lead.query.count()
        campaign_count = Campaign.query.count()
        if campaign_count == 0:
            return False, "Database accessible but 0 campaigns found"
        return True, f"DB OK ({lead_count} leads, {campaign_count} campaigns)"
    except Exception as e:
        return False, f"Database error: {e}"


def check_smtp():
    """Verify at least one active inbox can connect to SMTP."""
    from models import Inbox
    import smtplib

    inboxes = Inbox.query.filter_by(active=True).all()
    if not inboxes:
        return False, "No active inboxes configured"

    inbox = inboxes[0]
    try:
        if inbox.smtp_use_tls:
            server = smtplib.SMTP(inbox.smtp_host, inbox.smtp_port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(inbox.smtp_host, inbox.smtp_port, timeout=15)
        server.login(inbox.username, inbox.password)
        server.quit()
        return True, f"SMTP OK ({inbox.email})"
    except Exception as e:
        return False, f"SMTP failed for {inbox.email}: {e}"


def check_telegram():
    """Verify Telegram bot credentials are set."""
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — no alerts possible"
    return True, "Telegram configured"


def check_pending_responses():
    """Check if there are unprocessed responses piling up (systemic failure indicator)."""
    from models import Response
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(hours=4)
    stuck = Response.query.filter(
        Response.reviewed == False,
        Response.received_at < cutoff
    ).count()

    if stuck >= 3:
        return False, f"{stuck} responses unprocessed for 4h+ — AI auto-reply may be broken"
    if stuck > 0:
        return True, f"{stuck} response(s) pending 4h+ (monitoring)"
    return True, "No stuck responses"


def _send_alert(message):
    """Send Telegram alert directly (doesn't depend on app context)."""
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass


def run_all_checks(warn_only=False):
    """Run all health checks. Returns exit code (0=ok, 1=critical failure)."""
    checks = [
        ("OpenRouter API", check_openrouter_api_key, True),
        ("Database", check_database, True),
        ("SMTP", check_smtp, True),
        ("Telegram", check_telegram, False),
        ("Pending Responses", check_pending_responses, False),
    ]

    failures = []
    warnings = []

    for name, check_fn, is_critical in checks:
        try:
            ok, message = check_fn()
            if ok:
                logger.info(f"[{name}] PASS — {message}")
            elif is_critical:
                logger.error(f"[{name}] FAIL (CRITICAL) — {message}")
                failures.append((name, message))
            else:
                logger.warning(f"[{name}] WARN — {message}")
                warnings.append((name, message))
        except Exception as e:
            logger.error(f"[{name}] EXCEPTION — {e}")
            if is_critical:
                failures.append((name, str(e)))

    if failures:
        msg = "\U0001f534 <b>HEALTH CHECK FAILED</b>\n\n"
        for name, reason in failures:
            msg += f"<b>{name}:</b> {reason}\n"
        if warnings:
            msg += "\n<b>Warnings:</b>\n"
            for name, reason in warnings:
                msg += f"  {name}: {reason}\n"
        msg += "\n<b>Cron run aborted.</b> Fix the issue and re-trigger."
        _send_alert(msg)

        if warn_only:
            logger.warning("Critical failures found but --warn mode, continuing")
            return 0
        return 1

    if warnings:
        msg = "\u26a0\ufe0f <b>HEALTH CHECK WARNINGS</b>\n\n"
        for name, reason in warnings:
            msg += f"<b>{name}:</b> {reason}\n"
        _send_alert(msg)

    logger.info("All health checks passed")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Pre-flight health checks')
    parser.add_argument('--warn', action='store_true', help='Warn only, do not abort on critical failure')
    args = parser.parse_args()

    from app import app
    with app.app_context():
        exit_code = run_all_checks(warn_only=args.warn)

    sys.exit(exit_code)
