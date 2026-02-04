#!/usr/bin/env python3
"""
Telegram Email Notifier
Polls IMAP inbox and sends notifications to Telegram when new emails arrive.
More reliable than Spacemail's built-in forwarding.

Setup:
1. Create a Telegram bot via @BotFather, get the token
2. Get your chat ID by messaging @userinfobot
3. Set environment variables:
   - TELEGRAM_BOT_TOKEN=your_bot_token
   - TELEGRAM_CHAT_ID=your_chat_id
4. Run: python telegram_notifier.py

Can also run as a cron job or GitHub Action.
"""

import os
import sys
import time
import imaplib
import email
from email.header import decode_header
from datetime import datetime
import requests
import logging
from pathlib import Path

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
SEEN_EMAILS_FILE = Path(script_dir) / '.seen_emails'

# IMAP config from app
from app import app
from models import Inbox


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


def decode_mime_header(header):
    """Decode MIME encoded header."""
    if not header:
        return ""
    decoded_parts = decode_header(header)
    result = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or 'utf-8', errors='ignore'))
        else:
            result.append(part)
    return ''.join(result)


def get_email_body(msg):
    """Extract plain text body from email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except:
            body = str(msg.get_payload())
    return body.strip()[:500]  # Limit to 500 chars


def load_seen_emails():
    """Load set of seen email message IDs."""
    if SEEN_EMAILS_FILE.exists():
        return set(SEEN_EMAILS_FILE.read_text().strip().split('\n'))
    return set()


def save_seen_email(message_id: str):
    """Add message ID to seen emails."""
    seen = load_seen_emails()
    seen.add(message_id)
    # Keep only last 1000 to prevent file bloat
    if len(seen) > 1000:
        seen = set(list(seen)[-1000:])
    SEEN_EMAILS_FILE.write_text('\n'.join(seen))


def check_inbox_for_new_emails():
    """Check IMAP inbox for new emails and notify via Telegram."""
    with app.app_context():
        inboxes = Inbox.query.filter_by(active=True).all()

        for inbox in inboxes:
            logger.info(f"Checking inbox: {inbox.email}")

            try:
                # Connect to IMAP
                if inbox.imap_use_ssl:
                    mail = imaplib.IMAP4_SSL(inbox.imap_host, inbox.imap_port, timeout=30)
                else:
                    mail = imaplib.IMAP4(inbox.imap_host, inbox.imap_port, timeout=30)

                mail.login(inbox.username, inbox.password)
                mail.select('INBOX')

                # Search for all recent emails (last 24 hours would be SINCE)
                # Using UNSEEN for unread
                status, messages = mail.search(None, 'UNSEEN')

                if status != 'OK':
                    logger.warning(f"No messages found in {inbox.email}")
                    mail.logout()
                    continue

                message_ids = messages[0].split()
                seen_emails = load_seen_emails()

                for msg_id in message_ids:
                    try:
                        # Fetch email
                        status, msg_data = mail.fetch(msg_id, '(RFC822)')
                        if status != 'OK':
                            continue

                        # Parse email
                        email_body = msg_data[0][1]
                        msg = email.message_from_bytes(email_body)

                        # Get unique identifier
                        email_message_id = msg.get('Message-ID', str(msg_id))

                        # Skip if already notified
                        if email_message_id in seen_emails:
                            continue

                        # Extract details
                        from_addr = decode_mime_header(msg.get('From', ''))
                        subject = decode_mime_header(msg.get('Subject', '(No subject)'))
                        body = get_email_body(msg)
                        date_str = msg.get('Date', '')

                        # Format Telegram message
                        notification = f"""<b>New Email Reply!</b>

<b>From:</b> {from_addr}
<b>Subject:</b> {subject}
<b>To:</b> {inbox.email}
<b>Time:</b> {date_str}

<b>Preview:</b>
{body[:300]}{'...' if len(body) > 300 else ''}

---
Reply in Spacemail or forward to handle."""

                        # Send notification
                        if send_telegram_message(notification):
                            save_seen_email(email_message_id)
                            logger.info(f"Notified about email from {from_addr}")

                        # Don't mark as read - let the cron_runner handle that
                        # mail.store(msg_id, '+FLAGS', '\\Seen')

                    except Exception as e:
                        logger.error(f"Error processing message {msg_id}: {e}")
                        continue

                mail.logout()

            except Exception as e:
                logger.error(f"Error checking inbox {inbox.email}: {e}")


def check_lead_status():
    """Check lead counts and alert if running low."""
    with app.app_context():
        from models import CampaignLead, Campaign, SentEmail

        campaigns = Campaign.query.filter_by(status='active').all()

        for campaign in campaigns:
            # Count leads by status
            active_leads = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                status='active'
            ).count()

            completed_leads = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                status='completed'
            ).count()

            stopped_leads = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                status='stopped'
            ).count()

            total_leads = active_leads + completed_leads + stopped_leads

            # Count emails sent today
            from datetime import datetime, timedelta
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
            emails_today = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= today_start
            ).count()

            # Alert thresholds
            if active_leads == 0:
                send_telegram_message(
                    f"🚨 <b>OUT OF LEADS!</b>\n\n"
                    f"Campaign: {campaign.name}\n"
                    f"Active leads: 0\n"
                    f"Completed: {completed_leads}\n"
                    f"Stopped (replied): {stopped_leads}\n\n"
                    f"Add more leads to continue outreach."
                )
            elif active_leads <= 50:
                send_telegram_message(
                    f"⚠️ <b>Low Leads Warning</b>\n\n"
                    f"Campaign: {campaign.name}\n"
                    f"Active leads remaining: {active_leads}\n"
                    f"Completed: {completed_leads}\n"
                    f"Stopped (replied): {stopped_leads}\n\n"
                    f"Consider adding more leads soon."
                )

            logger.info(f"Campaign '{campaign.name}': {active_leads} active, {completed_leads} completed, {stopped_leads} stopped")


def send_daily_summary():
    """Send daily campaign summary."""
    with app.app_context():
        from models import CampaignLead, Campaign, SentEmail, Response
        from datetime import datetime, timedelta

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
            total_responses = Response.query.join(SentEmail).filter(
                SentEmail.campaign_id == campaign.id
            ).count()

            reply_rate = (total_responses / total_sent * 100) if total_sent > 0 else 0

            send_telegram_message(
                f"📊 <b>Daily Summary</b>\n\n"
                f"<b>{campaign.name}</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Emails sent today: {emails_today}\n"
                f"Total sent: {total_sent}\n"
                f"Replies: {total_responses} ({reply_rate:.1f}%)\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Active leads: {active}\n"
                f"Completed: {completed}\n"
                f"Stopped: {stopped}"
            )


def run_daemon(interval_seconds=60):
    """Run as a daemon, checking every N seconds."""
    logger.info(f"Starting Telegram notifier daemon (interval: {interval_seconds}s)")

    while True:
        try:
            check_inbox_for_new_emails()
        except Exception as e:
            logger.error(f"Error in check loop: {e}")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Telegram Email Notifier')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon (continuous)')
    parser.add_argument('--interval', type=int, default=60, help='Check interval in seconds (default: 60)')
    parser.add_argument('--once', action='store_true', help='Check emails once and exit')
    parser.add_argument('--test', action='store_true', help='Send a test notification')
    parser.add_argument('--leads', action='store_true', help='Check lead status and alert if low')
    parser.add_argument('--summary', action='store_true', help='Send daily campaign summary')
    parser.add_argument('--all', action='store_true', help='Run all checks (emails + leads)')

    args = parser.parse_args()

    if args.test:
        if send_telegram_message("✅ <b>Test notification</b>\n\nWedding Counselors CRM notifications are working!"):
            print("Test notification sent successfully!")
        else:
            print("Failed to send test notification. Check your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        sys.exit(0)

    if args.summary:
        send_daily_summary()
        print("Daily summary sent.")
        sys.exit(0)

    if args.daemon:
        run_daemon(args.interval)
    elif args.all:
        check_inbox_for_new_emails()
        check_lead_status()
        print("All checks complete.")
    elif args.leads:
        check_lead_status()
        print("Lead status check complete.")
    else:
        check_inbox_for_new_emails()
        print("Email check complete.")
