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
from email_templates import wrap_email_html, build_unsubscribe_url
from config import Config

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Run lightweight migrations before any queries
with app.app_context():
    _ensure_response_columns()


# ─── Supabase signup check ───────────────────────────────────────────────
# Query the Wedding Counselors website database to see if a lead already
# signed up. Prevents embarrassing "did you sign up?" emails to people
# who are already on the platform.

_supabase_client = None

def _get_supabase():
    """Lazy-init Supabase client. Returns None if not configured."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    url = os.environ.get('SUPABASE_URL') or os.environ.get('REACT_APP_SUPABASE_URL', '')
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if not url or not key:
        logger.warning("Supabase not configured — skipping website signup checks")
        _supabase_client = False  # sentinel: tried and failed
        return None
    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        logger.info("Supabase client initialized for signup checks")
        return _supabase_client
    except Exception as e:
        logger.warning(f"Could not init Supabase client: {e}")
        _supabase_client = False
        return None


def is_already_signed_up(email: str) -> bool:
    """Check if this email has a profile on the Wedding Counselors website."""
    sb = _get_supabase()
    if not sb:
        return False
    try:
        result = sb.table("profiles").select("id, is_claimed").ilike("email", email.strip()).execute()
        if result.data:
            logger.info(f"Lead {email} already has a profile on the website (is_claimed={result.data[0].get('is_claimed')})")
            return True
        # Note: auth.users is not accessible via PostgREST (schema restriction).
        # The profiles table check above is sufficient — every signed-up user
        # gets a profile row via the Supabase trigger.
        return False
    except Exception as e:
        logger.warning(f"Supabase lookup failed for {email}: {e}")
        return False  # fail open — don't block sends on Supabase errors


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

        # Enforce daily send cap — use local timezone (not UTC) to match sending hours
        tz = ZoneInfo(Config.TIMEZONE)
        local_now = datetime.now(tz)
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = local_midnight.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
        sent_today = SentEmail.query.filter(
            SentEmail.sent_at >= today_start_utc,
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

                # Skip if lead already signed up on the website
                if lead.status != 'signed_up' and is_already_signed_up(lead.email):
                    lead.status = 'signed_up'
                    cl.status = 'completed'
                    db.session.commit()
                    logger.info(f"Skipping {lead.email} — already signed up on website")
                    continue
                if lead.status == 'signed_up':
                    cl.status = 'completed'
                    db.session.commit()
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

                    # Wrap in professional HTML template with brand footer
                    body_html = wrap_email_html(body, inbox.email, lead=lead)
                    unsubscribe_url = build_unsubscribe_url(lead)

                    sender = EmailSender(inbox)
                    success, message_id, error = sender.send_email(
                        to_email=lead.email,
                        subject=subject,
                        body_html=body_html,
                        unsubscribe_url=unsubscribe_url
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

                        # Store personal deadline on first email so AI responder
                        # can use the exact date this lead was told (not a hardcoded global date)
                        if next_sequence.step_number == 1 and not lead.personal_deadline:
                            deadline_date = datetime.utcnow() + timedelta(days=21)
                            day = deadline_date.day
                            suffix = ('th' if 11 <= day <= 13
                                      else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th'))
                            lead.personal_deadline = deadline_date.strftime(f'%B {day}{suffix}')

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


def _parse_ooo_return_date(body: str) -> str:
    """Try to extract a return date from an OOO message body. Returns YYYY-MM-DD or ''."""
    import re
    from datetime import datetime as _dt

    # Common patterns: "return on March 5", "back on 3/5/2026", "returning February 25th"
    patterns = [
        # "return/back on March 5, 2026" or "March 5th"
        r'(?:return|back|available|office)\s+(?:on|by)?\s*'
        r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4})',
        # "return/back on 3/5/2026" or "3/5/26" or "03/05/2026"
        r'(?:return|back|available|office)\s+(?:on|by)?\s*(\d{1,2}/\d{1,2}/\d{2,4})',
        # "return/back on 2026-03-05"
        r'(?:return|back|available|office)\s+(?:on|by)?\s*(\d{4}-\d{2}-\d{2})',
        # Standalone date mention near OOO keywords: "I will be out until March 5"
        r'(?:until|through|till)\s+'
        r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4})',
        r'(?:until|through|till)\s+(\d{1,2}/\d{1,2}/\d{2,4})',
    ]

    body_clean = body.lower().replace('\n', ' ').replace('\r', ' ')

    for pattern in patterns:
        match = re.search(pattern, body_clean, re.IGNORECASE)
        if not match:
            continue
        date_str = match.group(1).strip().rstrip(',')
        # Remove ordinal suffixes
        date_str = re.sub(r'(\d)(st|nd|rd|th)', r'\1', date_str)

        # Try parsing common formats
        for fmt in [
            '%B %d %Y', '%B %d, %Y', '%B %d',
            '%b %d %Y', '%b %d, %Y', '%b %d',
            '%b. %d %Y', '%b. %d, %Y', '%b. %d',
            '%m/%d/%Y', '%m/%d/%y',
            '%Y-%m-%d',
        ]:
            try:
                parsed = _dt.strptime(date_str, fmt)
                # If no year in format, assume current or next year
                if '%Y' not in fmt and '%y' not in fmt:
                    now = _dt.utcnow()
                    parsed = parsed.replace(year=now.year)
                    if parsed < now - timedelta(days=30):
                        parsed = parsed.replace(year=now.year + 1)
                return parsed.strftime('%Y-%m-%d')
            except ValueError:
                continue

    return ''


def check_responses():
    """Check for email responses and record new ones in the DB."""
    logger.info("Starting response check job...")
    import re

    with app.app_context():
        inboxes = Inbox.query.filter_by(active=True).all()
        new_responses = 0

        for inbox in inboxes:
            try:
                receiver = EmailReceiver(inbox)
                responses = receiver.fetch_new_responses()

                for resp_data in responses:
                    in_reply_to = resp_data.get('in_reply_to')
                    sent_email = None
                    lead = None

                    # --- Match via In-Reply-To header ---
                    if in_reply_to:
                        # Try as-is (stripped of angle brackets by email_handler)
                        sent_email = SentEmail.query.filter_by(message_id=in_reply_to).first()
                        # Try with angle brackets (message_ids are stored with brackets)
                        if not sent_email:
                            sent_email = SentEmail.query.filter_by(message_id=f'<{in_reply_to}>').first()
                        if sent_email:
                            lead = sent_email.lead

                    # --- Fallback: match by sender email address ---
                    from_field = resp_data.get('from', '')
                    email_match = re.search(r'[\w\.-]+@[\w\.-]+', from_field)
                    from_email = email_match.group(0) if email_match else None

                    if not lead and from_email:
                        lead = Lead.query.filter_by(email=from_email).first()

                    # Skip emails from ourselves or unknown senders
                    if not lead:
                        continue

                    # --- Duplicate check ---
                    msg_id = resp_data.get('message_id')
                    if msg_id:
                        existing = Response.query.filter_by(message_id=msg_id).first()
                        if existing:
                            continue

                    # --- Create new response record ---
                    response = Response(
                        lead_id=lead.id,
                        sent_email_id=sent_email.id if sent_email else None,
                        message_id=msg_id,
                        in_reply_to=in_reply_to,
                        subject=resp_data.get('subject'),
                        body=resp_data.get('body'),
                        reviewed=False
                    )

                    # --- OOO return date detection ---
                    body_lower = (resp_data.get('body') or '').lower()
                    subject_lower = (resp_data.get('subject') or '').lower()
                    combined = subject_lower + ' ' + body_lower
                    is_ooo = any(x in combined for x in [
                        'out of office', 'auto-reply', 'automatic reply',
                        'on vacation', 'away from', 'out of the office'
                    ])
                    if is_ooo:
                        return_date = _parse_ooo_return_date(resp_data.get('body') or '')
                        if return_date:
                            response.notes = f"OOO_RETURN:{return_date}"
                            logger.info(f"OOO detected for {lead.email}, return date: {return_date}")

                    db.session.add(response)

                    lead.status = 'responded'

                    # Stop active campaigns for this lead
                    campaign_leads = CampaignLead.query.filter_by(
                        lead_id=lead.id,
                        status='active'
                    ).all()
                    for cl in campaign_leads:
                        cl.status = 'stopped'

                    db.session.commit()
                    new_responses += 1
                    logger.info(f"NEW RESPONSE from {lead.email} (lead {lead.id}): {resp_data.get('subject', '')[:60]}")

            except Exception as e:
                logger.error(f"Error checking inbox {inbox.email}: {e}")

    logger.info(f"Response check job completed: {new_responses} new response(s) recorded")


def auto_reply():
    """Run AI auto-reply on unreviewed responses."""
    logger.info("Starting AI auto-reply job...")
    with app.app_context():
        try:
            from ai_responder import AutoReplyScheduler
            scheduler = AutoReplyScheduler(app=app, db=db)
            count = scheduler.process_pending_responses()
            logger.info(f"Auto-reply job completed: {count} replies sent")
        except Exception as e:
            logger.error(f"Error in auto-reply job: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run email jobs')
    parser.add_argument('--send', action='store_true', help='Send scheduled emails')
    parser.add_argument('--check', action='store_true', help='Check for responses')
    parser.add_argument('--reply', action='store_true', help='Run AI auto-reply')
    parser.add_argument('--all', action='store_true', help='Run all jobs')

    args = parser.parse_args()

    if args.all or (not args.send and not args.check and not args.reply):
        send_scheduled_emails()
        check_responses()
        auto_reply()
    else:
        if args.send:
            send_scheduled_emails()
        if args.check:
            check_responses()
        if args.reply:
            auto_reply()

    print("Done!")
