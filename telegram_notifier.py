#!/usr/bin/env python3
"""
Telegram Notifier — Real-time campaign updates

Sends Telegram notifications for:
- New email replies (from DB responses, tracked via `notified` column)
- AI auto-reply confirmations
- Lead status alerts
- Daily campaign summary

Uses database `notified` column to track which responses have been
notified, so state persists across GitHub Actions runs.
"""

import os
import sys
import logging
from datetime import datetime, timedelta

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

from app import app, _ensure_response_columns
from models import db, Inbox, Response, Lead, CampaignLead, Campaign, SentEmail

# Run lightweight migrations before any queries
with app.app_context():
    _ensure_response_columns()


def send_telegram_message(message: str) -> bool:
    """Send a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram notification sent")
            return True
        else:
            logger.error(f"Telegram API error: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def check_new_responses():
    """Safety-net notification for responses the AI responder didn't handle.

    The AI responder is the primary notification source — it sets
    notified=True after sending its own Telegram alert. This function
    only picks up responses that somehow slipped through (e.g. AI
    responder didn't run, or a new response arrived between steps).

    Uses the `notified` boolean column on the Response model so that
    notification state persists in the database.
    """
    with app.app_context():
        # Only notify about responses the AI responder hasn't already handled
        pending = Response.query.filter_by(notified=False).order_by(
            Response.received_at.desc()
        ).limit(50).all()

        new_count = 0

        for resp in pending:
            lead = resp.lead
            if not lead:
                resp.notified = True
                db.session.commit()
                continue

            # If AI already reviewed this, it should have set notified=True.
            # If we're here with reviewed=True but notified=False, just fix the flag.
            if resp.reviewed:
                resp.notified = True
                db.session.commit()
                continue

            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            company = lead.company or ""
            body_preview = (resp.body or "")[:300]
            body_preview = body_preview.replace('<', '&lt;').replace('>', '&gt;')
            name = name.replace('<', '&lt;').replace('>', '&gt;')

            notification = (
                f"<b>New Reply (unprocessed)</b>\n\n"
                f"<b>From:</b> {name}"
                + (f" ({company})" if company else "") + "\n"
                f"<b>Email:</b> {lead.email}\n"
                f"<b>Subject:</b> {resp.subject or '(no subject)'}\n\n"
                f"<b>Message:</b>\n{body_preview}"
                + ("..." if len(resp.body or "") > 300 else "")
            )

            if send_telegram_message(notification):
                resp.notified = True
                db.session.commit()
                new_count += 1
                logger.info(f"Notified (safety-net): reply from {lead.email}")

        if new_count > 0:
            logger.info(f"Sent {new_count} safety-net notifications")
        else:
            logger.info("No unprocessed responses to notify about")


def check_lead_status():
    """Check lead counts and alert if running low."""
    with app.app_context():
        campaigns = Campaign.query.filter_by(status='active').all()

        for campaign in campaigns:
            active = CampaignLead.query.filter_by(
                campaign_id=campaign.id, status='active'
            ).count()
            completed = CampaignLead.query.filter_by(
                campaign_id=campaign.id, status='completed'
            ).count()
            stopped = CampaignLead.query.filter_by(
                campaign_id=campaign.id, status='stopped'
            ).count()

            if active == 0:
                send_telegram_message(
                    f"<b>OUT OF LEADS</b>\n\n"
                    f"Campaign: {campaign.name}\n"
                    f"Active leads: 0\n"
                    f"Completed: {completed}\n"
                    f"Replied/stopped: {stopped}\n\n"
                    f"Add more leads to continue outreach."
                )
            elif active <= 20:
                send_telegram_message(
                    f"<b>Low Leads Warning</b>\n\n"
                    f"Campaign: {campaign.name}\n"
                    f"Active leads remaining: {active}\n"
                    f"Completed: {completed}\n"
                    f"Replied/stopped: {stopped}"
                )

            logger.info(f"Campaign '{campaign.name}': {active} active, {completed} completed, {stopped} stopped")


def send_daily_summary():
    """Send daily campaign summary with all key stats."""
    with app.app_context():
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
        campaigns = Campaign.query.filter_by(status='active').all()

        for campaign in campaigns:
            active = CampaignLead.query.filter_by(campaign_id=campaign.id, status='active').count()
            completed = CampaignLead.query.filter_by(campaign_id=campaign.id, status='completed').count()
            stopped = CampaignLead.query.filter_by(campaign_id=campaign.id, status='stopped').count()

            emails_today = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= today_start
            ).count()

            total_sent = SentEmail.query.filter_by(campaign_id=campaign.id).count()

            # Count responses — use lead-based lookup so responses without
            # a sent_email_id are still counted
            campaign_lead_ids = db.session.query(CampaignLead.lead_id).filter_by(
                campaign_id=campaign.id
            ).subquery()
            total_responses = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids)
            ).count()

            # Count AI auto-replies
            ai_replied = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.notes.like('%AI auto-replied%')
            ).count()

            reply_rate = (total_responses / total_sent * 100) if total_sent > 0 else 0

            send_telegram_message(
                f"<b>Daily Summary</b>\n\n"
                f"<b>{campaign.name}</b>\n"
                f"{'='*20}\n"
                f"Emails sent today: {emails_today}\n"
                f"Total sent: {total_sent}\n"
                f"Replies: {total_responses} ({reply_rate:.1f}%)\n"
                f"AI auto-replied: {ai_replied}\n"
                f"{'='*20}\n"
                f"Active leads: {active}\n"
                f"Completed: {completed}\n"
                f"Replied/stopped: {stopped}"
            )


def send_weekly_digest():
    """Send comprehensive weekly report — designed for Sunday evenings."""
    with app.app_context():
        now = datetime.utcnow()
        week_start = now - timedelta(days=7)

        campaigns = Campaign.query.filter_by(status='active').all()

        # --- Aggregate stats across all campaigns ---
        total_sent_week = 0
        total_sent_alltime = 0
        total_replies_week = 0
        total_replies_alltime = 0
        total_ai_replied = 0
        total_active_leads = 0
        total_stopped = 0
        total_completed = 0
        campaign_blocks = []

        for campaign in campaigns:
            active = CampaignLead.query.filter_by(campaign_id=campaign.id, status='active').count()
            completed = CampaignLead.query.filter_by(campaign_id=campaign.id, status='completed').count()
            stopped = CampaignLead.query.filter_by(campaign_id=campaign.id, status='stopped').count()

            sent_week = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= week_start
            ).count()

            sent_alltime = SentEmail.query.filter_by(campaign_id=campaign.id).count()

            # Use lead-based lookup for response counts
            campaign_lead_ids = db.session.query(CampaignLead.lead_id).filter_by(
                campaign_id=campaign.id
            ).subquery()

            replies_week = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.received_at >= week_start
            ).count()

            replies_alltime = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids)
            ).count()

            ai_replied = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.notes.like('%AI auto-replied%')
            ).count()

            reply_rate = (replies_alltime / sent_alltime * 100) if sent_alltime > 0 else 0
            week_rate = (replies_week / sent_week * 100) if sent_week > 0 else 0

            total_sent_week += sent_week
            total_sent_alltime += sent_alltime
            total_replies_week += replies_week
            total_replies_alltime += replies_alltime
            total_ai_replied += ai_replied
            total_active_leads += active
            total_stopped += stopped
            total_completed += completed

            campaign_blocks.append(
                f"<b>{campaign.name}</b>\n"
                f"  Sent this week: {sent_week}\n"
                f"  Replies this week: {replies_week}"
                + (f" ({week_rate:.1f}%)" if sent_week > 0 else "") + "\n"
                f"  Leads: {active} active / {stopped} replied / {completed} done"
            )

        # --- Estimated days until leads exhausted ---
        if total_sent_week > 0:
            daily_rate = total_sent_week / 7
            days_remaining = int(total_active_leads / daily_rate) if daily_rate > 0 else 999
            runway = f"~{days_remaining} days at current pace"
        else:
            runway = "N/A (no sends this week)"

        # --- Top responders this week ---
        recent_responses = Response.query.filter(
            Response.received_at >= week_start
        ).order_by(Response.received_at.desc()).limit(10).all()

        responder_lines = []
        for resp in recent_responses:
            lead = resp.lead
            if not lead:
                continue
            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            name = name.replace('<', '&lt;').replace('>', '&gt;')
            status_tag = ""
            if resp.notes and "AI auto-replied" in resp.notes:
                status_tag = " [AI replied]"
            elif resp.reviewed:
                status_tag = " [reviewed]"
            responder_lines.append(f"  {name}{status_tag}")

        # --- Build the digest ---
        overall_rate = (total_replies_alltime / total_sent_alltime * 100) if total_sent_alltime > 0 else 0

        msg = (
            f"<b>WEEKLY DIGEST</b>\n"
            f"{now.strftime('%b %d, %Y')}\n"
            f"{'='*25}\n\n"
            f"<b>THIS WEEK</b>\n"
            f"  Emails sent: {total_sent_week}\n"
            f"  Replies received: {total_replies_week}\n"
            f"  AI auto-replies sent: {total_ai_replied}\n\n"
            f"<b>ALL TIME</b>\n"
            f"  Total sent: {total_sent_alltime}\n"
            f"  Total replies: {total_replies_alltime} ({overall_rate:.1f}%)\n\n"
            f"<b>PIPELINE</b>\n"
            f"  Active leads remaining: {total_active_leads}\n"
            f"  Lead runway: {runway}\n\n"
        )

        # Add campaign breakdowns
        if campaign_blocks:
            msg += "<b>BY CAMPAIGN</b>\n"
            msg += "\n".join(campaign_blocks)
            msg += "\n\n"

        # Add recent responders
        if responder_lines:
            msg += "<b>RECENT REPLIES</b>\n"
            msg += "\n".join(responder_lines[:8])

        send_telegram_message(msg)
        logger.info("Weekly digest sent")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Telegram Notifier')
    parser.add_argument('--once', action='store_true', help='Check new responses once')
    parser.add_argument('--test', action='store_true', help='Send test notification')
    parser.add_argument('--leads', action='store_true', help='Check lead status')
    parser.add_argument('--summary', action='store_true', help='Send daily summary')
    parser.add_argument('--weekly', action='store_true', help='Send weekly digest')
    parser.add_argument('--all', action='store_true', help='Run all checks')

    args = parser.parse_args()

    if args.test:
        if send_telegram_message("<b>Test notification</b>\n\nWedding Counselors notifications are working."):
            print("Test notification sent.")
        else:
            print("Failed to send. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        sys.exit(0)

    if args.weekly:
        send_weekly_digest()
        print("Weekly digest sent.")
        sys.exit(0)

    if args.summary:
        send_daily_summary()
        print("Daily summary sent.")
        sys.exit(0)

    if args.all:
        check_new_responses()
        check_lead_status()
        print("All checks complete.")
    elif args.leads:
        check_lead_status()
        print("Lead status check complete.")
    else:
        check_new_responses()
        print("Response check complete.")
