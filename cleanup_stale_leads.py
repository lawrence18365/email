#!/usr/bin/env python3
"""
Cleanup stale leads that received the broken "directory listing" subject.

These leads got a bad first impression (0% reply rate subject line) and
have been stuck for 11+ days. Mark them as completed so they stop clogging
the pipeline. Their emails are logged for potential re-import into a fresh
campaign later.

Run via: GitHub Actions → "Update WC Sequences" workflow_dispatch
         (runs before sequence updates)
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app import app
from models import db, CampaignLead, SentEmail


def main():
    print("Cleaning up leads that received 'directory listing' subject...\n")

    with app.app_context():
        cutoff = datetime.utcnow() - timedelta(days=10)
        active_cls = CampaignLead.query.filter_by(status='active').all()

        cleaned = 0
        cleaned_emails = []

        for cl in active_cls:
            # Find the last email sent to this lead in this campaign
            last_sent = SentEmail.query.filter_by(
                lead_id=cl.lead_id,
                campaign_id=cl.campaign_id
            ).order_by(SentEmail.sent_at.desc()).first()

            if not last_sent:
                continue

            # Check: sent 10+ days ago with the bad subject
            subject_lower = (last_sent.subject or '').lower()
            if last_sent.sent_at < cutoff and 'directory listing' in subject_lower:
                lead = cl.lead
                cl.status = 'completed'
                db.session.commit()
                cleaned += 1
                cleaned_emails.append(lead.email)
                print(f"  Cleaned: {lead.email} (campaign {cl.campaign_id}, subject: {last_sent.subject!r})")

        print(f"\nTotal cleaned: {cleaned}")

        if cleaned_emails:
            print(f"\nCleaned emails (for potential re-import):")
            for email in cleaned_emails:
                print(f"  {email}")

        # Send Telegram summary
        try:
            import requests
            token = os.environ.get('TELEGRAM_BOT_TOKEN')
            chat_id = os.environ.get('TELEGRAM_CHAT_ID')
            if token and chat_id and cleaned > 0:
                msg = (
                    f"\U0001f9f9 <b>Stale Lead Cleanup</b>\n\n"
                    f"Marked {cleaned} leads as completed.\n"
                    f"These received the broken 'directory listing' subject 10+ days ago.\n"
                    f"Pipeline is now clean for fresh outreach."
                )
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10
                )
        except Exception as e:
            logger.warning(f"Could not send Telegram cleanup summary: {e}")


if __name__ == "__main__":
    main()
