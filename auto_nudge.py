#!/usr/bin/env python3
"""
AUTO NUDGE — Automated follow-up for warm leads who expressed interest
but haven't signed up yet.

Runs as part of the hourly cron. Automatically:
1. Finds leads who responded with interest but haven't signed up
2. Checks Supabase to confirm they haven't registered
3. Crafts personalized AI nudges based on conversation history
4. Sends threaded follow-ups (appears in same email thread)
5. Tracks sends to prevent over-nudging

Nudge eligibility:
- Lead status = 'responded'
- We sent the last message (they haven't replied)
- Last interaction was 3+ days ago
- Haven't been nudged in the last 7 days
- Max 3 nudges per lead total

Run:  python auto_nudge.py             # from cron (respects hours)
      python auto_nudge.py --force     # ignore time checks
      python auto_nudge.py --dry-run   # preview only
"""
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app import app, _ensure_response_columns
from models import db, Lead, Response, SentEmail, CampaignLead, Campaign, Sequence, Inbox
from email_handler import EmailSender
from email_templates import build_unsubscribe_url
from config import Config

# Run lightweight migrations
with app.app_context():
    _ensure_response_columns()

# ─── Configuration ─────────────────────────────────────────────────────────────

def _parse_ooo_return(notes: str):
    """Extract OOO return date from response notes (format: OOO_RETURN:YYYY-MM-DD)."""
    import re
    match = re.search(r'OOO_RETURN:(\d{4}-\d{2}-\d{2})', notes or '')
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


NUDGE_COOLDOWN_DAYS = 5       # Min days between nudges to same lead
NUDGE_MAX_PER_LEAD = 6        # Max total nudges per lead
NUDGE_MIN_AGE_DAYS = 3        # Min days since last interaction before nudging
NUDGE_PER_RUN_CAP = 8         # Max nudges per cron run
NUDGE_SENDING_HOURS = (9, 17) # 9am–5pm PT, ANY day of the week (warm leads)

SIGNUP_LINK = (
    "https://www.weddingcounselors.com/professional/signup"
    "?utm_source=email&utm_medium=nudge&utm_campaign=auto_nudge"
)


def is_nudge_time(force=False):
    """Check if now is within nudge sending hours (any day, 9–5 PT)."""
    if force:
        return True
    tz = ZoneInfo(Config.TIMEZONE)
    now = datetime.now(tz)
    return NUDGE_SENDING_HOURS[0] <= now.hour < NUDGE_SENDING_HOURS[1]


def get_nudge_candidates():
    """Find leads eligible for a nudge follow-up."""
    candidates = []
    now = datetime.utcnow()

    # All leads with status='responded' — they showed interest but haven't signed up
    responded_leads = Lead.query.filter(Lead.status == 'responded').all()
    logger.info(f"Checking {len(responded_leads)} responded leads for nudge eligibility")

    for lead in responded_leads:
        # Get latest response and latest send
        last_response = Response.query.filter_by(
            lead_id=lead.id
        ).order_by(Response.received_at.desc()).first()

        if not last_response:
            continue

        last_sent = SentEmail.query.filter_by(
            lead_id=lead.id, status='sent'
        ).order_by(SentEmail.sent_at.desc()).first()

        if not last_sent:
            continue

        # Skip if latest response notes indicate negative intent
        if last_response.notes:
            notes_lower = last_response.notes.lower()
            if any(neg in notes_lower for neg in ['not_interested', 'unsubscribe']):
                continue
            # OOO: skip only if return date hasn't passed yet
            if 'out_of_office' in notes_lower:
                ooo_return = _parse_ooo_return(last_response.notes)
                if ooo_return and ooo_return > datetime.utcnow().date():
                    continue
                # Return date has passed (or wasn't set) — they're back, eligible for nudge

        # We must have sent the last message (our AI reply) and they haven't responded to it
        last_response_time = last_response.received_at or datetime.min
        if last_sent.sent_at <= last_response_time:
            # They sent the last message — auto-reply system should handle this, not nudge
            continue

        # How long since our last send?
        days_since = (now - last_sent.sent_at).days
        if days_since < NUDGE_MIN_AGE_DAYS:
            continue

        # Count nudges: sends after their first response, minus expected auto-replies
        first_response = Response.query.filter_by(
            lead_id=lead.id
        ).order_by(Response.received_at.asc()).first()
        first_response_time = first_response.received_at or datetime.min

        sends_after_response = SentEmail.query.filter(
            SentEmail.lead_id == lead.id,
            SentEmail.sent_at > first_response_time,
            SentEmail.status == 'sent'
        ).count()

        response_count = Response.query.filter_by(lead_id=lead.id).count()
        # Each response triggers ~1 auto-reply. Extra sends are nudges.
        nudge_count = max(0, sends_after_response - response_count)

        if nudge_count >= NUDGE_MAX_PER_LEAD:
            logger.info(f"Skipping {lead.email}: max nudges reached ({nudge_count}/{NUDGE_MAX_PER_LEAD})")
            continue

        # Cooldown: don't nudge if we sent a Re: email recently
        if last_sent.subject and last_sent.subject.lower().startswith('re:'):
            if days_since < NUDGE_COOLDOWN_DAYS:
                logger.info(f"Skipping {lead.email}: cooldown ({days_since}d < {NUDGE_COOLDOWN_DAYS}d)")
                continue

        candidates.append({
            'lead': lead,
            'last_response': last_response,
            'last_sent': last_sent,
            'days_since': days_since,
            'nudge_count': nudge_count,
        })

    # Sort by oldest first (longest-waiting leads get nudged first)
    candidates.sort(key=lambda c: c['days_since'], reverse=True)
    return candidates


def build_conversation_history(lead):
    """Build readable conversation history for AI context."""
    all_sent = SentEmail.query.filter_by(
        lead_id=lead.id, status='sent'
    ).order_by(SentEmail.sent_at).all()

    all_responses = Response.query.filter_by(
        lead_id=lead.id
    ).order_by(Response.received_at).all()

    # Interleave by time
    events = []
    for s in all_sent:
        events.append(('US', s.sent_at, s.subject, s.body))
    for r in all_responses:
        ts = r.received_at or datetime.min
        events.append(('THEM', ts, r.subject, r.body))
    events.sort(key=lambda e: e[1])

    lines = []
    for who, when, subject, body in events[-6:]:  # Last 6 messages
        when_str = when.strftime('%b %d') if when != datetime.min else '?'
        body_preview = (body or '')[:400].strip()
        lines.append(f"[{when_str}] {who}: {subject}\n{body_preview}")

    return "\n\n".join(lines)


def generate_nudge_text(lead, conversation_history, nudge_count):
    """Use AI to craft a personalized nudge email."""
    from ai_responder import AIResponder, _build_system_prompt

    responder = AIResponder()

    first_name = lead.first_name or 'there'
    deadline = lead.personal_deadline or 'March 15th'

    system = _build_system_prompt('hello@weddingcounselors.com')
    system += f"""

## NUDGE CONTEXT
You are writing a FOLLOW-UP nudge to a warm lead who previously expressed interest
but hasn't signed up yet. This is nudge #{nudge_count + 1}.

Rules:
- Be brief (3-5 sentences max). This is a quick personal check-in.
- Reference something specific from their conversation (show you remember them)
- Include the signup link naturally: {SIGNUP_LINK}
- Mention the founding member deadline ({deadline}) if it fits naturally
- Sound like a real person checking in, not a sales template
- If this is nudge #2+, be even lighter touch / shorter
- Sign off as: Sarah\\nWedding Counselors Directory
- Output ONLY the plain email body text — no subject line, no JSON, no markdown
- Do NOT include "Subject:" or any headers — just the email body"""

    prompt = f"""Write a brief follow-up nudge to {first_name} ({lead.email}).

Their conversation history:
{conversation_history}

This is follow-up #{nudge_count + 1} since they expressed interest. They haven't signed up yet.
Days since last contact: {(datetime.utcnow() - (lead.updated_at or datetime.utcnow())).days}

Craft a short, personal check-in that references their specific conversation."""

    reply = responder._call_ai(system, prompt, max_tokens=512)
    return reply


def send_nudge(lead, nudge_text, dry_run=False):
    """Send the nudge email threaded into the existing conversation."""
    if dry_run:
        name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
        print(f"\n{'='*60}")
        print(f"TO:   {name} <{lead.email}>")
        print(f"{'─'*60}")
        print(nudge_text)
        print(f"{'='*60}")
        return True

    # Find campaign context for this lead
    cl = CampaignLead.query.filter_by(lead_id=lead.id).first()
    if not cl:
        logger.error(f"No CampaignLead for {lead.email}")
        return False

    campaign = Campaign.query.get(cl.campaign_id)
    if not campaign:
        logger.error(f"No campaign for {lead.email}")
        return False

    inbox = campaign.inbox
    if not inbox or not inbox.active:
        inbox = Inbox.query.filter_by(active=True).first()
    if not inbox:
        logger.error(f"No active inbox for nudge to {lead.email}")
        return False

    # Get sequence for FK reference
    sequence = Sequence.query.filter_by(campaign_id=campaign.id).first()
    if not sequence:
        logger.error(f"No sequence for campaign {campaign.id}")
        return False

    # Find the last sent email to thread into
    last_sent = SentEmail.query.filter_by(
        lead_id=lead.id, status='sent'
    ).order_by(SentEmail.sent_at.desc()).first()

    # Build subject (thread into existing conversation)
    if last_sent and last_sent.subject:
        subject = last_sent.subject if last_sent.subject.lower().startswith('re:') else f"Re: {last_sent.subject}"
    else:
        industry = lead.industry or 'premarital'
        subject = f"Re: founding member spot for {industry} counselors"

    # Threading headers
    reply_to_id = None
    ref_chain = None

    last_response = Response.query.filter_by(
        lead_id=lead.id
    ).order_by(Response.received_at.desc()).first()

    if last_response and last_response.message_id:
        reply_to_id = last_response.message_id
        if not reply_to_id.startswith('<'):
            reply_to_id = f'<{reply_to_id}>'
    elif last_sent and last_sent.message_id:
        reply_to_id = last_sent.message_id
        if not reply_to_id.startswith('<'):
            reply_to_id = f'<{reply_to_id}>'

    if last_sent and last_sent.message_id:
        ref_chain = last_sent.message_id
        if reply_to_id and reply_to_id != ref_chain:
            ref_chain = f'{ref_chain} {reply_to_id}'
    elif reply_to_id:
        ref_chain = reply_to_id

    # Send
    unsubscribe_url = build_unsubscribe_url(lead)
    bcc_email = os.getenv('NOTIFICATION_BCC_EMAIL')

    sender = EmailSender(inbox)
    success, message_id, error = sender.send_email(
        to_email=lead.email,
        subject=subject,
        body_html=nudge_text.replace('\n', '<br>'),
        bcc=bcc_email,
        in_reply_to=reply_to_id,
        references=ref_chain,
        unsubscribe_url=unsubscribe_url
    )

    if success:
        sent_record = SentEmail(
            lead_id=lead.id,
            campaign_id=campaign.id,
            sequence_id=sequence.id,
            inbox_id=inbox.id,
            message_id=message_id,
            subject=subject,
            body=nudge_text,
            status='sent'
        )
        db.session.add(sent_record)
        db.session.commit()
        logger.info(f"Nudge sent to {lead.email} (message_id={message_id})")
        return True
    else:
        logger.error(f"Failed to send nudge to {lead.email}: {error}")
        return False


def notify_nudge_sent(lead, nudge_text, nudge_count, days_since):
    """Send Telegram notification about the nudge."""
    try:
        import requests
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return

        def _esc(s):
            return (s or '').replace('<', '&lt;').replace('>', '&gt;')

        name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
        company = _esc(lead.company or '')
        preview = _esc(nudge_text[:200].strip())

        who_line = _esc(name)
        if company:
            who_line += f" | {company}"

        msg = (
            f"📩 <b>AUTO NUDGE SENT</b>\n\n"
            f"<b>{who_line}</b>\n"
            f"{lead.email}\n"
            f"Nudge #{nudge_count + 1} | Silent for {days_since}d\n\n"
            f"\"{preview}{'...' if len(nudge_text) > 200 else ''}\""
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Telegram notify failed: {e}")


def notify_nudge_summary(sent_count, candidate_count):
    """Send summary Telegram notification after nudge run."""
    if sent_count == 0:
        return
    try:
        import requests
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return

        msg = (
            f"📊 <b>Auto Nudge Summary</b>\n\n"
            f"Sent: {sent_count}/{candidate_count} candidates\n"
            f"Remaining: {candidate_count - sent_count} (cap or filtered)"
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass


def run_auto_nudge(force=False, dry_run=False):
    """Main entry point for the auto-nudge system."""
    logger.info("Starting auto-nudge job...")

    if not is_nudge_time(force):
        tz = ZoneInfo(Config.TIMEZONE)
        now = datetime.now(tz)
        logger.info(
            f"Outside nudge hours ({NUDGE_SENDING_HOURS[0]}-{NUDGE_SENDING_HOURS[1]} PT, "
            f"current={now.hour}:{now.minute:02d}). Skipping."
        )
        return 0

    with app.app_context():
        # Import Supabase check to prevent nudging people who already signed up
        try:
            from cron_runner import is_already_signed_up
        except ImportError:
            is_already_signed_up = lambda _: False

        candidates = get_nudge_candidates()
        logger.info(f"Found {len(candidates)} nudge candidates")

        if dry_run:
            print(f"\n{'='*60}")
            print(f"AUTO NUDGE — DRY RUN")
            print(f"Candidates: {len(candidates)}")
            print(f"Cap: {NUDGE_PER_RUN_CAP} per run")
            print(f"{'='*60}")

        sent = 0
        for c in candidates:
            if sent >= NUDGE_PER_RUN_CAP:
                logger.info(f"Per-run nudge cap reached ({NUDGE_PER_RUN_CAP})")
                break

            lead = c['lead']

            # Double-check: haven't signed up on website
            if is_already_signed_up(lead.email):
                lead.status = 'signed_up'
                db.session.commit()
                logger.info(f"Skipping {lead.email} — already signed up on website")
                continue

            # Build conversation context
            history = build_conversation_history(lead)

            # Generate AI nudge
            nudge_text = generate_nudge_text(lead, history, c['nudge_count'])
            if not nudge_text:
                logger.warning(f"AI failed to generate nudge for {lead.email}")
                continue

            # Send
            if send_nudge(lead, nudge_text, dry_run=dry_run):
                sent += 1
                if not dry_run:
                    notify_nudge_sent(lead, nudge_text, c['nudge_count'], c['days_since'])
                    logger.info(
                        f"[{sent}/{NUDGE_PER_RUN_CAP}] Nudged {lead.email} "
                        f"(silent {c['days_since']}d, nudge #{c['nudge_count'] + 1})"
                    )

                # Delay between sends
                if not dry_run and sent < NUDGE_PER_RUN_CAP:
                    time.sleep(5)

        if not dry_run:
            notify_nudge_summary(sent, len(candidates))

        logger.info(f"Auto-nudge complete: {sent} nudge(s) sent out of {len(candidates)} candidates")
        return sent


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Auto-nudge warm leads')
    parser.add_argument('--force', action='store_true', help='Ignore time checks')
    parser.add_argument('--dry-run', action='store_true', help='Preview only')
    args = parser.parse_args()

    run_auto_nudge(force=args.force, dry_run=args.dry_run)
