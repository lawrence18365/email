#!/usr/bin/env python3
"""
Cron runner for GitHub Actions.
Runs email sending and response checking jobs.
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Ensure we're in the right directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app, _ensure_response_columns
from models import db, Lead, Inbox, Campaign, Sequence, CampaignLead, SentEmail, Response
from email_handler import EmailSender, EmailReceiver, EmailPersonalizer, RateLimiter
from config import Config

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Run lightweight migrations before any queries
with app.app_context():
    _ensure_response_columns()


def is_within_sending_hours():
    """Check if current time is within allowed sending hours (Mon-Fri only)"""
    tz = ZoneInfo(Config.TIMEZONE)
    now = datetime.now(tz)
    hour = now.hour
    # Only send outreach Mon-Fri (0=Monday, 6=Sunday)
    if now.weekday() >= 5:
        return False
    return Config.DEFAULT_SENDING_HOURS_START <= hour < Config.DEFAULT_SENDING_HOURS_END


def send_scheduled_emails():
    """Send emails for active campaigns"""
    logger.info("Starting scheduled email send job...")

    if not is_within_sending_hours():
        logger.info(f"Outside sending hours ({Config.DEFAULT_SENDING_HOURS_START}-{Config.DEFAULT_SENDING_HOURS_END}). Skipping.")
        return

    with app.app_context():
        rate_limiter = RateLimiter(db.session)
        personalizer = EmailPersonalizer()

        # Enforce daily send cap (matches Verifalia free tier: 25/day)
        today_start = datetime.combine(datetime.utcnow().date(), datetime.min.time())
        sent_today = SentEmail.query.filter(
            SentEmail.sent_at >= today_start,
            SentEmail.status == 'sent'
        ).count()
        daily_cap = int(os.environ.get('DAILY_SEND_CAP', '25'))
        if sent_today >= daily_cap:
            logger.info(f"Daily send cap reached ({sent_today}/{daily_cap}). Stopping.")
            return
        remaining_today = daily_cap - sent_today
        sent_this_run = 0

        # Get active campaigns
        active_campaigns = Campaign.query.filter_by(status='active').all()
        logger.info(f"Found {len(active_campaigns)} active campaigns")

        for campaign in active_campaigns:
            inbox = campaign.inbox
            if not inbox or not inbox.active:
                logger.warning(f"Campaign {campaign.id} has no active inbox")
                continue

            # Check rate limit
            if not rate_limiter.can_send(inbox.id, inbox.max_per_hour):
                logger.info(f"Rate limit reached for inbox {inbox.email}")
                continue

            # Get active leads in this campaign
            campaign_leads = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                status='active'
            ).all()

            for cl in campaign_leads:
                lead = cl.lead

                # Skip if lead has responded
                if lead.status == 'responded':
                    continue

                # Get last sent email for this lead in this campaign
                last_sent = SentEmail.query.filter_by(
                    lead_id=lead.id,
                    campaign_id=campaign.id
                ).order_by(SentEmail.sent_at.desc()).first()

                # Determine next sequence step
                if last_sent:
                    last_step = last_sent.sequence.step_number
                    next_sequence = Sequence.query.filter_by(
                        campaign_id=campaign.id,
                        step_number=last_step + 1,
                        active=True
                    ).first()

                    if not next_sequence:
                        # All sequences completed for this lead
                        cl.status = 'completed'
                        db.session.commit()
                        continue

                    # Check if delay has passed
                    delay_days = next_sequence.delay_days
                    if datetime.utcnow() < last_sent.sent_at + timedelta(days=delay_days):
                        continue
                else:
                    # First email - get step 1
                    next_sequence = Sequence.query.filter_by(
                        campaign_id=campaign.id,
                        step_number=1,
                        active=True
                    ).first()

                    if not next_sequence:
                        continue

                # Re-check rate limit before sending
                if not rate_limiter.can_send(inbox.id, inbox.max_per_hour):
                    logger.info(f"Rate limit reached for inbox {inbox.email}")
                    break

                # Verify email before sending (Verifalia - 25 free/day)
                from email_verifier import EmailVerifier
                verifier = EmailVerifier(db.session)
                verification_status = verifier.verify_email(lead)
                if not verifier.should_send(verification_status):
                    logger.warning(f"Skipping {lead.email}: verification={verification_status}")
                    cl.status = 'stopped'
                    db.session.commit()
                    continue

                # Personalize and send email
                try:
                    subject = personalizer.personalize(next_sequence.subject_template, lead)
                    body = personalizer.personalize(next_sequence.email_template, lead)

                    sender = EmailSender(inbox)
                    success, message_id, error = sender.send_email(
                        to_email=lead.email,
                        subject=subject,
                        body_html=body.replace('\n', '<br>')
                    )

                    if success:
                        # Record sent email
                        sent_email = SentEmail(
                            lead_id=lead.id,
                            campaign_id=campaign.id,
                            sequence_id=next_sequence.id,
                            inbox_id=inbox.id,
                            message_id=message_id,
                            subject=subject,
                            body=body,
                            status='sent'
                        )
                        db.session.add(sent_email)

                        # Update lead status
                        if lead.status == 'new':
                            lead.status = 'contacted'

                        db.session.commit()
                        logger.info(f"Sent email to {lead.email} (step {next_sequence.step_number})")

                        sent_this_run += 1
                        if sent_this_run >= remaining_today:
                            logger.info(f"Daily send cap reached ({sent_today + sent_this_run}/{daily_cap}). Stopping.")
                            return
                    else:
                        logger.error(f"Failed to send to {lead.email}: {error}")

                except Exception as e:
                    logger.error(f"Error sending to {lead.email}: {e}")

    logger.info("Scheduled email send job completed")


def check_responses():
    """Check for email responses"""
    logger.info("Starting response check job...")

    with app.app_context():
        # Get active inboxes
        inboxes = Inbox.query.filter_by(active=True).all()

        for inbox in inboxes:
            try:
                receiver = EmailReceiver(inbox)
                responses = receiver.fetch_new_responses()

                for resp_data in responses:
                    # Try to match to a sent email
                    in_reply_to = resp_data.get('in_reply_to')
                    sent_email = None
                    lead = None

                    if in_reply_to:
                        sent_email = SentEmail.query.filter_by(message_id=in_reply_to).first()
                        if sent_email:
                            lead = sent_email.lead

                    if not lead:
                        # Try to find lead by sender email
                        from_field = resp_data.get('from', '')
                        # Extract email from "Name <email>" format
                        import re
                        email_match = re.search(r'[\w\.-]+@[\w\.-]+', from_field)
                        if email_match:
                            from_email = email_match.group(0)
                            lead = Lead.query.filter_by(email=from_email).first()

                    if lead:
                        # Check for duplicate
                        existing = Response.query.filter_by(message_id=resp_data.get('message_id')).first()
                        if existing:
                            continue

                        # Create response record
                        response = Response(
                            lead_id=lead.id,
                            sent_email_id=sent_email.id if sent_email else None,
                            message_id=resp_data.get('message_id'),
                            in_reply_to=in_reply_to,
                            subject=resp_data.get('subject'),
                            body=resp_data.get('body'),
                            reviewed=False
                        )
                        db.session.add(response)

                        # Update lead status
                        lead.status = 'responded'

                        # Stop campaign for this lead
                        campaign_leads = CampaignLead.query.filter_by(
                            lead_id=lead.id,
                            status='active'
                        ).all()
                        for cl in campaign_leads:
                            cl.status = 'stopped'

                        db.session.commit()
                        logger.info(f"Recorded response from {lead.email}")

            except Exception as e:
                logger.error(f"Error checking inbox {inbox.email}: {e}")

    logger.info("Response check job completed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run email jobs')
    parser.add_argument('--send', action='store_true', help='Send scheduled emails')
    parser.add_argument('--check', action='store_true', help='Check for responses')
    parser.add_argument('--all', action='store_true', help='Run all jobs')

    args = parser.parse_args()

    if args.all or (not args.send and not args.check):
        send_scheduled_emails()
        check_responses()
    else:
        if args.send:
            send_scheduled_emails()
        if args.check:
            check_responses()

    print("Done!")
