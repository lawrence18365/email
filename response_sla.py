#!/usr/bin/env python3
"""
Response SLA Monitor — Ensures no lead goes unanswered.

Escalation tiers:
  1h+  unprocessed → log warning (AI should have handled it)
  4h+  unprocessed → URGENT Telegram alert
  24h+ unprocessed → CRITICAL Telegram alert with full context
  3+ stuck         → "AI SYSTEM BROKEN" diagnostic alert

Also checks for escalated-but-unreplied responses (AI punted to human
but human hasn't replied).

Runs every cron cycle after Telegram notifications.
"""

import os
import sys
import logging
from datetime import datetime, timedelta

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def _esc(s):
    return (s or '').replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')


def _send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, can't send SLA alert")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.error(f"Failed to send SLA Telegram alert: {e}")


def check_unprocessed_responses():
    """Check for responses the AI hasn't processed yet (reviewed=False)."""
    from models import Response

    now = datetime.utcnow()
    pending = Response.query.filter_by(reviewed=False).all()

    tier_1h = []
    tier_4h = []
    tier_24h = []

    for resp in pending:
        if not resp.received_at or not resp.lead:
            continue
        age_hours = (now - resp.received_at).total_seconds() / 3600
        lead = resp.lead

        entry = {
            'email': lead.email,
            'name': f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
            'age_hours': age_hours,
            'preview': _esc((resp.body or '')[:200]),
            'notes': resp.notes or '',
        }

        if age_hours >= 24:
            tier_24h.append(entry)
        elif age_hours >= 4:
            tier_4h.append(entry)
        elif age_hours >= 1:
            tier_1h.append(entry)

    # --- Systemic failure: 3+ responses stuck means AI is broken ---
    total_stuck = len(tier_1h) + len(tier_4h) + len(tier_24h)
    if total_stuck >= 3:
        msg = (
            "\U0001f534 <b>AI AUTO-REPLY SYSTEM APPEARS BROKEN</b>\n\n"
            f"{total_stuck} responses stuck (unprocessed):\n"
            f"  24h+: {len(tier_24h)}\n"
            f"  4h+: {len(tier_4h)}\n"
            f"  1h+: {len(tier_1h)}\n\n"
            "<b>Diagnostic checklist:</b>\n"
            "1. Is OPENROUTER_API_KEY set in GitHub Secrets?\n"
            "2. Check cron logs for 'No OPENROUTER_API_KEY' errors\n"
            "3. Run <b>Force Process Pending Replies</b> workflow\n"
            "4. Check OpenRouter dashboard for quota/billing issues"
        )
        _send_telegram(msg)
        logger.error(f"SLA: {total_stuck} responses stuck — AI system may be broken")

    # --- CRITICAL: 24h+ unanswered ---
    if tier_24h:
        msg = f"\U0001f6a8 <b>CRITICAL: {len(tier_24h)} RESPONSE(S) UNANSWERED 24h+</b>\n\n"
        for e in tier_24h[:5]:
            msg += f"<b>{_esc(e['name'])}</b> | {_esc(e['email'])} | {int(e['age_hours'])}h\n"
            if e['preview']:
                msg += f'"{e["preview"][:150]}"\n'
            if e['notes']:
                msg += f"<i>Notes: {_esc(e['notes'][:100])}</i>\n"
            msg += "\n"
        if len(tier_24h) > 5:
            msg += f"...and {len(tier_24h) - 5} more\n"
        msg += "\n<b>ACTION:</b> Reply manually or run Force Reply workflow."
        _send_telegram(msg)

    # --- URGENT: 4h+ unanswered ---
    if tier_4h:
        msg = f"\u26a0\ufe0f <b>URGENT: {len(tier_4h)} response(s) waiting 4h+</b>\n\n"
        for e in tier_4h[:8]:
            msg += f"  {_esc(e['name'])} | {int(e['age_hours'])}h"
            if e['notes']:
                msg += f" | {_esc(e['notes'][:60])}"
            msg += "\n"
        _send_telegram(msg)

    # --- INFO: 1h+ just log ---
    for e in tier_1h:
        logger.warning(f"SLA: Response from {e['email']} is {e['age_hours']:.1f}h old, still unprocessed")

    return total_stuck


def check_escalated_unreplied():
    """Check for responses that AI escalated to human but human hasn't replied."""
    from models import Response, SentEmail

    now = datetime.utcnow()
    escalated = Response.query.filter(
        Response.reviewed == True,
        Response.notes.like('%needs human review%')
    ).order_by(Response.received_at.asc()).all()

    unreplied_24h = []

    for resp in escalated:
        lead = resp.lead
        if not lead or not resp.received_at:
            continue

        # Check if we sent a reply after this response
        replied = SentEmail.query.filter(
            SentEmail.lead_id == lead.id,
            SentEmail.subject.like('Re:%'),
            SentEmail.sent_at >= resp.received_at
        ).first()
        if replied:
            continue

        age_hours = (now - resp.received_at).total_seconds() / 3600
        if age_hours >= 24:
            unreplied_24h.append({
                'email': lead.email,
                'name': f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                'age_hours': age_hours,
                'preview': _esc((resp.body or '')[:150]),
            })

    if unreplied_24h:
        msg = f"\U0001f4e2 <b>{len(unreplied_24h)} ESCALATED LEAD(S) — HUMAN REPLY NEEDED 24h+</b>\n\n"
        for e in unreplied_24h[:5]:
            msg += f"<b>{_esc(e['name'])}</b> | {int(e['age_hours'])}h waiting\n"
            if e['preview']:
                msg += f'"{e["preview"]}"\n'
            msg += "\n"
        if len(unreplied_24h) > 5:
            msg += f"...and {len(unreplied_24h) - 5} more\n"
        msg += "\n<b>These were escalated by the AI — only a human can reply.</b>"
        _send_telegram(msg)

    return len(unreplied_24h)


def main():
    from app import app

    with app.app_context():
        stuck = check_unprocessed_responses()
        unreplied = check_escalated_unreplied()

        if stuck == 0 and unreplied == 0:
            logger.info("SLA check: all clear — no stuck or unreplied responses")
        else:
            logger.warning(f"SLA check: {stuck} unprocessed, {unreplied} escalated-unreplied")


if __name__ == "__main__":
    main()
