"""
AI Email Responder — OpenRouter/Kimi K2.5 Powered

Reads incoming emails, understands intent, drafts personalized replies,
and sends them automatically. Uses AI_REPLY_CONTEXT.md as the single
source of truth for all factual claims.
"""

import os
import re
import json
import logging
import smtplib
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration — supports Kimi Code API (preferred) or OpenRouter fallback
KIMI_API_KEY = os.getenv('KIMI_API_KEY', '')
KIMI_ENDPOINT = "https://api.kimi.com/coding/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = os.getenv('AI_MODEL', 'kimi-k2.5')

# Load context document
CONTEXT_DOC_PATH = Path(__file__).parent / 'AI_REPLY_CONTEXT.md'
CONTEXT_DOC = ""
if CONTEXT_DOC_PATH.exists():
    CONTEXT_DOC = CONTEXT_DOC_PATH.read_text()
else:
    logger.warning(f"AI_REPLY_CONTEXT.md not found at {CONTEXT_DOC_PATH}")


class ResponseIntent:
    INTERESTED = "interested"
    MEETING_REQUEST = "meeting_request"
    QUESTION = "question"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    OUT_OF_OFFICE = "out_of_office"
    SPAM = "spam"
    BOUNCE = "bounce"
    UNCLEAR = "unclear"


SYSTEM_PROMPT = f"""You are an AI email assistant for Wedding Counselors Directory.
You MUST follow every rule in the context document below.
Do NOT say anything not covered by this document.
If something isn't in this doc, do NOT say it.

{CONTEXT_DOC}"""

INTENT_ANALYSIS_PROMPT = """Analyze this email and classify the sender's intent.

From: {from_name} ({from_email})
Subject: {subject}

Email body:
{body}

---
Classify as ONE of: interested, meeting_request, question, not_interested, unsubscribe, out_of_office, spam, bounce, unclear

Respond in JSON only:
{{"intent": "category", "sentiment": "positive/neutral/negative", "urgency": "high/medium/low", "key_points": ["point1"], "confidence": 0.0-1.0}}"""

REPLY_GENERATION_PROMPT = """Generate a reply to this email. Intent: {intent}

From: {from_name} <{from_email}>
Subject: {subject}

Their message:
{body}

IMPORTANT RULES:
- Follow the context document rules exactly
- For interested, question, conditional, and meeting_request intents: ALWAYS include the signup link (https://www.weddingcounselors.com/professional/signup) as a clear call-to-action
- For not_interested and unsubscribe: do NOT include the signup link
- Write at a Fortune 500 level — polished, professional, concise. No fluff
- Output ONLY the plain email body text — no subject line, no JSON, no markdown"""


class AIResponder:
    """AI-powered email response system using OpenRouter/Kimi"""

    def __init__(self, db_session=None):
        self.db = db_session
        if not KIMI_API_KEY and not OPENROUTER_API_KEY:
            logger.warning("No AI API key set (KIMI_API_KEY or OPENROUTER_API_KEY) — AI responder will not function")

    def _call_ai(self, system: str, user: str, max_tokens: int = 1024) -> Optional[str]:
        """Make an API call to Kimi Code API (preferred) or OpenRouter fallback."""
        # Pick provider: Kimi Code first, OpenRouter fallback
        if KIMI_API_KEY:
            api_key = KIMI_API_KEY
            endpoint = KIMI_ENDPOINT
            provider = "Kimi"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        elif OPENROUTER_API_KEY:
            api_key = OPENROUTER_API_KEY
            endpoint = OPENROUTER_ENDPOINT
            provider = "OpenRouter"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://weddingcounselors.com",
                "X-Title": "Wedding Counselors Auto-Reply",
            }
        else:
            logger.error("No AI API key configured")
            return None

        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.7
                },
                timeout=120
            )

            if resp.status_code == 200:
                data = resp.json()
                content = data['choices'][0]['message']['content']
                if content:
                    return content.strip()
                logger.warning("AI returned empty content")
                return None
            else:
                logger.error(f"{provider} API error: {resp.status_code} — {resp.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"AI call failed ({provider}): {e}")
            return None

    def analyze_intent(self, email_data: Dict) -> Dict:
        """Analyze the intent of an incoming email."""
        # Quick heuristic checks first (no API call needed)
        body = (email_data.get('body') or '').lower()
        subject = (email_data.get('subject') or '').lower()
        from_email = (email_data.get('from_email') or '').lower()

        # Bounce detection
        if any(x in from_email for x in ['mailer-daemon', 'postmaster', 'mail delivery']):
            return {"intent": ResponseIntent.BOUNCE, "sentiment": "neutral",
                    "urgency": "low", "key_points": ["bounce"], "confidence": 1.0}

        # Out of office
        if any(x in subject + body for x in ['out of office', 'auto-reply', 'automatic reply', 'on vacation']):
            return {"intent": ResponseIntent.OUT_OF_OFFICE, "sentiment": "neutral",
                    "urgency": "low", "key_points": ["ooo"], "confidence": 0.95}

        # Unsubscribe
        if any(x in body for x in ['unsubscribe', 'remove me', 'opt out', 'stop emailing']):
            return {"intent": ResponseIntent.UNSUBSCRIBE, "sentiment": "negative",
                    "urgency": "high", "key_points": ["unsubscribe"], "confidence": 0.9}

        # AI-powered analysis for everything else
        prompt = INTENT_ANALYSIS_PROMPT.format(**email_data)
        result = self._call_ai("You are an email intent classifier. Respond in JSON only.", prompt, max_tokens=512)

        if result:
            try:
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    analysis = json.loads(json_match.group())
                    logger.info(f"Analyzed {email_data['from_email']}: intent={analysis.get('intent')}")
                    return analysis
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse AI intent response")

        return {"intent": ResponseIntent.UNCLEAR, "sentiment": "neutral",
                "urgency": "medium", "key_points": [], "confidence": 0.0}

    def generate_reply(self, email_data: Dict, analysis: Dict) -> Optional[str]:
        """Generate a reply based on intent analysis."""
        intent = analysis.get('intent', '')

        # Skip these — no reply needed
        if intent in [ResponseIntent.OUT_OF_OFFICE, ResponseIntent.SPAM, ResponseIntent.BOUNCE]:
            logger.info(f"Skipping reply for {intent}")
            return None

        # Unsubscribe — quick template, no AI needed
        if intent == ResponseIntent.UNSUBSCRIBE:
            name = email_data.get('from_name', '').split()[0] if email_data.get('from_name') else 'there'
            return f"""Hi {name},

I've removed you from our mailing list. You won't receive any further emails from us.

Apologies for the inconvenience.

Sarah, Wedding Counselors Directory"""

        # AI-generated reply for everything else
        prompt = REPLY_GENERATION_PROMPT.format(
            intent=intent,
            from_name=email_data.get('from_name', ''),
            from_email=email_data.get('from_email', ''),
            subject=email_data.get('subject', ''),
            body=email_data.get('body', '')
        )

        reply = self._call_ai(SYSTEM_PROMPT, prompt)
        if reply:
            logger.info(f"Generated reply for {email_data['from_email']} (intent: {intent})")
        return reply

    def should_auto_send(self, analysis: Dict) -> bool:
        """Determine if reply should be auto-sent."""
        if analysis.get('confidence', 0) < 0.5:
            return False
        if analysis.get('intent') in [ResponseIntent.SPAM, ResponseIntent.OUT_OF_OFFICE, ResponseIntent.BOUNCE]:
            return False
        return True


class AutoReplyScheduler:
    """Processes pending responses and sends AI replies."""

    def __init__(self, app=None, db=None):
        self.app = app
        self.db = db
        self.responder = AIResponder()

    def process_pending_responses(self) -> int:
        """Process all unreviewed responses and send AI replies."""
        from models import Response, Lead, SentEmail, Inbox
        from email_handler import EmailSender

        replies_sent = 0

        with self.app.app_context():
            pending = Response.query.filter_by(reviewed=False).all()
            logger.info(f"Found {len(pending)} unreviewed responses")

            for response in pending:
                try:
                    lead = response.lead
                    if not lead:
                        response.reviewed = True
                        self.db.session.commit()
                        continue

                    # Build email data
                    email_data = {
                        "from_name": lead.full_name if hasattr(lead, 'full_name') else f"{lead.first_name or ''} {lead.last_name or ''}".strip(),
                        "from_email": lead.email,
                        "subject": response.subject or "",
                        "body": response.body or ""
                    }

                    # Analyze intent
                    analysis = self.responder.analyze_intent(email_data)
                    intent = analysis.get('intent', 'unclear')

                    # Generate reply
                    reply_text = self.responder.generate_reply(email_data, analysis)

                    if not reply_text:
                        response.reviewed = True
                        response.notified = True
                        response.notes = f"AI: {intent} — no reply needed"
                        self.db.session.commit()
                        continue

                    # Check if should auto-send
                    if not self.responder.should_auto_send(analysis):
                        response.notified = True
                        response.notes = f"AI draft (needs review, confidence={analysis.get('confidence', 0):.2f}): {reply_text[:200]}..."
                        self.db.session.commit()
                        logger.info(f"Reply queued for review: {lead.email}")
                        continue

                    # Get inbox and campaign context
                    sent_email = response.sent_email
                    inbox = None
                    campaign_id = None
                    sequence_id = None

                    if sent_email:
                        inbox = sent_email.inbox
                        campaign_id = sent_email.campaign_id
                        sequence_id = sent_email.sequence_id

                    if not inbox:
                        inbox = Inbox.query.filter_by(active=True).first()

                    # If no campaign/sequence from sent_email, find from lead's history
                    if not campaign_id or not sequence_id:
                        from models import CampaignLead as CL
                        cl = CL.query.filter_by(lead_id=lead.id).first()
                        if cl and not campaign_id:
                            campaign_id = cl.campaign_id
                        # Find any sequence for this campaign to satisfy NOT NULL
                        if campaign_id and not sequence_id:
                            from models import Sequence
                            seq = Sequence.query.filter_by(campaign_id=campaign_id).first()
                            if seq:
                                sequence_id = seq.id

                    if not inbox or not campaign_id or not sequence_id:
                        logger.error(f"Missing inbox/campaign/sequence for reply to {lead.email}")
                        response.reviewed = True
                        response.notified = True
                        response.notes = f"AI: {intent} — could not send (missing campaign context)"
                        self.db.session.commit()
                        continue

                    # Send the reply
                    sender = EmailSender(inbox)
                    original_subject = response.subject or "Your inquiry"
                    reply_subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"

                    success, message_id, error = sender.send_email(
                        to_email=lead.email,
                        subject=reply_subject,
                        body_html=reply_text.replace('\n', '<br>')
                    )

                    if success:
                        # Record sent reply
                        reply_record = SentEmail(
                            lead_id=lead.id,
                            campaign_id=campaign_id,
                            sequence_id=sequence_id,
                            inbox_id=inbox.id,
                            message_id=message_id,
                            subject=reply_subject,
                            body=reply_text,
                            status='sent'
                        )
                        self.db.session.add(reply_record)

                        # Mark response as reviewed and notified
                        response.reviewed = True
                        response.notified = True
                        response.notes = f"AI auto-replied ({intent})"

                        # Update lead status
                        if intent == ResponseIntent.MEETING_REQUEST:
                            lead.status = 'meeting_booked'
                        elif intent == ResponseIntent.NOT_INTERESTED:
                            lead.status = 'not_interested'
                        elif intent == ResponseIntent.UNSUBSCRIBE:
                            lead.status = 'not_interested'

                        self.db.session.commit()
                        replies_sent += 1

                        logger.info(f"Auto-replied to {lead.email} (intent: {intent})")

                        # Send Telegram notification about the auto-reply
                        _notify_auto_reply(lead, intent, reply_text)

                    else:
                        logger.error(f"Failed to send reply to {lead.email}: {error}")

                except Exception as e:
                    logger.error(f"Error processing response {response.id}: {str(e)}")
                    self.db.session.rollback()
                    _notify_failure(lead if lead else None, str(e))
                    continue

        return replies_sent


def _notify_auto_reply(lead, intent, reply_text):
    """Send a Telegram notification when an AI reply is sent."""
    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return

        preview = reply_text[:200].replace('<', '&lt;').replace('>', '&gt;')
        name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email

        msg = (
            f"<b>AI Auto-Reply Sent</b>\n\n"
            f"<b>To:</b> {name} ({lead.email})\n"
            f"<b>Intent:</b> {intent}\n\n"
            f"<b>Reply preview:</b>\n{preview}..."
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Telegram notify failed: {e}")


def _notify_failure(lead, error_msg):
    """Send Telegram notification when AI reply fails."""
    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return

        email = lead.email if lead else "unknown"
        error_short = error_msg[:200].replace('<', '&lt;').replace('>', '&gt;')

        msg = (
            f"<b>AI Reply Failed</b>\n\n"
            f"<b>Lead:</b> {email}\n"
            f"<b>Error:</b> {error_short}"
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass


def run_auto_replies():
    """Standalone function to run auto-replies (for cron_runner)."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import app, _ensure_response_columns
    from models import db

    with app.app_context():
        _ensure_response_columns()

    scheduler = AutoReplyScheduler(app=app, db=db)
    count = scheduler.process_pending_responses()
    logger.info(f"Auto-reply job complete: {count} replies sent")
    return count


if __name__ == "__main__":
    run_auto_replies()
