"""
AI Email Responder — OpenRouter Pony Alpha Powered

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

# Configuration — OpenRouter API (free tier via Pony Alpha)
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
AI_MODEL = os.getenv('AI_MODEL', 'google/gemini-2.0-flash-001')
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Load context documents per brand
_CONTEXT_DIR = Path(__file__).parent
CONTEXT_DOCS = {}

_wc_path = _CONTEXT_DIR / 'AI_REPLY_CONTEXT.md'
if _wc_path.exists():
    CONTEXT_DOCS['weddingcounselors.com'] = _wc_path.read_text()

_rt_path = _CONTEXT_DIR / 'AI_REPLY_CONTEXT_RATETAP.md'
if _rt_path.exists():
    CONTEXT_DOCS['ratetapmx.com'] = _rt_path.read_text()

# Fallback: use WC context if nothing matches
CONTEXT_DOC = CONTEXT_DOCS.get('weddingcounselors.com', '')

if not CONTEXT_DOCS:
    logger.warning("No AI_REPLY_CONTEXT docs found")


def _get_brand_context(inbox_email: str) -> tuple:
    """Return (context_doc, brand_label) based on inbox email domain."""
    domain = (inbox_email or '').split('@')[-1].lower()
    if domain in CONTEXT_DOCS:
        label = 'RateTap' if 'ratetap' in domain else 'Wedding Counselors Directory'
        return CONTEXT_DOCS[domain], label
    return CONTEXT_DOC, 'Wedding Counselors Directory'


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
    CONVERSATION_COMPLETE = "conversation_complete"  # "thanks", "got it", etc.

# Short, conversation-ending messages that don't need a reply.
# Checked against stripped/lowered body text.
CONVERSATION_ENDERS = [
    "thanks", "thank you", "thanks!", "thank you!", "thx", "ty",
    "got it", "got it!", "sounds good", "sounds great", "sounds good!",
    "will do", "will do!", "perfect", "perfect!", "great thanks",
    "great, thanks", "great thank you", "awesome thanks", "awesome, thanks",
    "appreciate it", "much appreciated", "noted", "ok thanks", "ok thank you",
    "okay thanks", "okay, thanks", "thanks so much", "thank you so much",
    "thanks a lot", "wonderful", "wonderful!", "excellent", "excellent!",
    "cool thanks", "cool, thanks", "thanks for the info",
    "thanks for the information", "will check it out", "i'll check it out",
    "i will check it out", "looking forward to it",
]

# Max words for a message to qualify as a conversation-ender.
# Longer messages likely contain real questions even if they start with "thanks".
ENDER_MAX_WORDS = 12

# Positive intent heuristics — these NEVER need an AI call.
# Short affirmative messages that clearly signal interest.
INTERESTED_PHRASES = [
    "yes", "yes please", "yes!", "yes please!", "yes, please",
    "sure", "sure!", "absolutely", "absolutely!",
    "im interested", "i'm interested", "i am interested",
    "interested", "interested!", "very interested",
    "sign me up", "sign me up!", "count me in", "count me in!",
    "i'd love to", "id love to", "i would love to",
    "i'd like to", "id like to", "i would like to",
    "sounds great sign me up", "yes sign me up",
    "please do", "please!", "lets do it", "let's do it",
    "i want in", "i'm in", "im in",
    "go ahead", "please proceed", "yes i would",
    "yes i do", "yes i am", "yes absolutely",
    "i'd love to be included", "i would love to be included",
    "love to", "would love to",
]

# Question intent heuristics — asking for more info.
QUESTION_PHRASES = [
    "tell me more", "more information", "more info",
    "can i get more information", "can you tell me more",
    "what does it cost", "how much", "how much does it cost",
    "what are the details", "send me details", "send me more info",
    "what do i need to do", "how do i sign up", "how does it work",
    "what is this", "whats this about", "what's this about",
    "can you explain", "id like to know more", "i'd like to know more",
    "i have some questions", "i have a question",
]

# Max words for short-message heuristic matching
HEURISTIC_MAX_WORDS = 15


def _build_system_prompt(inbox_email: str = '') -> str:
    """Build system prompt with brand-appropriate context."""
    context, brand = _get_brand_context(inbox_email)
    return f"""You are an AI email assistant for {brand}.
You MUST follow every rule in the context document below.
Do NOT say anything not covered by this document.
If something isn't in this doc, do NOT say it.

{context}"""

# Default system prompt (Wedding Counselors) for backward compatibility
SYSTEM_PROMPT = _build_system_prompt()

INTENT_ANALYSIS_PROMPT = """Analyze this email and classify the sender's intent.

From: {from_name} ({from_email})
Subject: {subject}

Email body:
{body}

---
Classify as ONE of: interested, meeting_request, question, not_interested, unsubscribe, out_of_office, spam, bounce, unclear

IMPORTANT classification rules:
- If someone has signed up, is using the platform, reports a bug, gives feedback, or makes a suggestion → "interested" (they are an ACTIVE user)
- If someone says they'll do it later, "this week", or "soon" → "interested"
- If someone reports frustration with signup, a form, or a technical issue → "question" (they need help)
- If someone asks about cost, pricing, or what's included → "question"
- Only use "unclear" if you genuinely cannot determine ANY intent from the message
- Confidence should be 0.8+ for any message where the person is clearly engaged

Respond in JSON only:
{{"intent": "category", "sentiment": "positive/neutral/negative", "urgency": "high/medium/low", "key_points": ["point1"], "confidence": 0.0-1.0}}"""

REPLY_GENERATION_PROMPT = """Generate a reply to this email. Intent: {intent}

From: {from_name} <{from_email}>
Subject: {subject}

Their message:
{body}

IMPORTANT RULES:
- Follow the context document rules exactly
- For interested, question, conditional, and meeting_request intents: ALWAYS end with the signup/CTA link and a clear reason to act NOW (deadline, limited spots, etc.)
- Every reply to an engaged lead MUST include the CTA link — never leave it out
- Create urgency using real deadlines and facts from the context doc — don't fabricate
- For not_interested and unsubscribe: do NOT include any links
- Write at a Fortune 500 level — polished, professional, concise. No fluff
- Output ONLY the plain email body text — no subject line, no JSON, no markdown"""


class AIResponder:
    """AI-powered email response system using Google Gemini"""

    def __init__(self, db_session=None):
        self.db = db_session
        self._last_error = None  # Tracks API failures vs intentional skips
        if not OPENROUTER_API_KEY:
            logger.warning("OPENROUTER_API_KEY not set — AI responder will not function")

    def _call_ai(self, system: str, user: str, max_tokens: int = 1024) -> Optional[str]:
        """Make an API call to OpenRouter (OpenAI-compatible) with retry for rate limits."""
        if not OPENROUTER_API_KEY:
            logger.error("No OPENROUTER_API_KEY configured")
            self._last_error = "no_api_key"
            return None

        import time
        max_retries = 3

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    OPENROUTER_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://ratetapmx.com",
                        "X-Title": "RateTap CRM"
                    },
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
                    # Handle both standard and edge-case response formats
                    content = None
                    if 'choices' in data and data['choices']:
                        msg = data['choices'][0].get('message') or {}
                        content = msg.get('content')
                    elif 'error' in data:
                        logger.error(f"OpenRouter returned error in 200: {data['error']}")
                        self._last_error = "api_error_in_200"
                        if attempt < max_retries - 1:
                            time.sleep((attempt + 1) * 10)
                            continue
                        return None

                    if content:
                        self._last_error = None
                        return content.strip()
                    logger.warning(f"OpenRouter returned empty/unexpected response: {str(data)[:200]}")
                    self._last_error = "empty_response"
                    if attempt < max_retries - 1:
                        time.sleep((attempt + 1) * 10)
                        continue
                    return None
                elif resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    logger.warning(f"OpenRouter rate limit (429), retry {attempt+1}/{max_retries} in {wait}s")
                    if attempt < max_retries - 1:
                        time.sleep(wait)
                        continue
                    logger.error(f"OpenRouter rate limit exhausted after {max_retries} retries")
                    self._last_error = "rate_limit"
                    return None
                else:
                    logger.error(f"OpenRouter API error: {resp.status_code} — {resp.text[:200]}")
                    self._last_error = f"api_error_{resp.status_code}"
                    return None

            except Exception as e:
                logger.error(f"AI call failed: {e}")
                self._last_error = "exception"
                return None

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

        # Clean body text for heuristic matching
        # First, strip quoted/forwarded email content (lines starting with >)
        # and everything after "On ... wrote:" patterns (quoted replies)
        body_no_quotes = re.sub(r'(?m)^>.*$', '', body)  # remove > quoted lines
        body_no_quotes = re.sub(r'on\s+.{10,80}\s+wrote:\s*[\s\S]*$', '', body_no_quotes, flags=re.IGNORECASE)  # remove "On ... wrote:" and everything after
        body_no_quotes = body_no_quotes.strip()

        # Strip email quoting, signatures, and whitespace
        body_clean = re.sub(r'[\>\s]+', ' ', body_no_quotes).strip()
        body_clean = re.sub(r'\s*--?\s*$', '', body_clean)
        body_clean = re.sub(r'(?:--|best|regards|sincerely|cheers|warm regards|notice:|confidential|disclaimer|this email|this message is intended)[\s\S]*$', '', body_clean, flags=re.IGNORECASE).strip()
        # Also strip common email signature patterns (name, title, phone, URL lines)
        body_clean = re.sub(r'(?:\*[^*]+\*\s*)+$', '', body_clean).strip()  # *Bold sig lines*
        body_clean = re.sub(r'(?:https?://\S+\s*)+$', '', body_clean).strip()  # trailing URLs
        body_clean = re.sub(r'[\d\.\-\(\)]{7,}\s*$', '', body_clean).strip()  # phone numbers
        word_count = len(body_clean.split())
        body_normalized = re.sub(r'[^\w\s]', '', body_clean).strip()

        # Unsubscribe — check cleaned body only (not raw body with quoted footers)
        # This prevents false positives from "Unsubscribe" links in quoted email footers
        if any(x in body_clean for x in ['unsubscribe', 'remove me', 'opt out', 'stop emailing']):
            return {"intent": ResponseIntent.UNSUBSCRIBE, "sentiment": "negative",
                    "urgency": "high", "key_points": ["unsubscribe"], "confidence": 0.9}

        # --- Interested heuristic (no API call needed) ---
        interested_normalized = [re.sub(r'[^\w\s]', '', p).strip() for p in INTERESTED_PHRASES]
        if word_count <= HEURISTIC_MAX_WORDS:
            if body_normalized in interested_normalized:
                logger.info(f"Heuristic match: INTERESTED for {from_email} — '{body_clean}'")
                return {"intent": ResponseIntent.INTERESTED, "sentiment": "positive",
                        "urgency": "high", "key_points": ["interested"], "confidence": 0.95}
        # Fallback: if body starts with an interested phrase (catches leftover signature text)
        for phrase in interested_normalized:
            if body_normalized.startswith(phrase) and len(phrase) >= 3:
                logger.info(f"Heuristic startswith match: INTERESTED for {from_email} — '{body_clean}'")
                return {"intent": ResponseIntent.INTERESTED, "sentiment": "positive",
                        "urgency": "high", "key_points": ["interested"], "confidence": 0.90}

        # --- Question heuristic (no API call needed) ---
        question_normalized = [re.sub(r'[^\w\s]', '', p).strip() for p in QUESTION_PHRASES]
        if word_count <= HEURISTIC_MAX_WORDS:
            if body_normalized in question_normalized:
                logger.info(f"Heuristic match: QUESTION for {from_email} — '{body_clean}'")
                return {"intent": ResponseIntent.QUESTION, "sentiment": "neutral",
                        "urgency": "medium", "key_points": ["question"], "confidence": 0.95}
        # Fallback: if body starts with a question phrase
        for phrase in question_normalized:
            if body_normalized.startswith(phrase) and len(phrase) >= 3:
                logger.info(f"Heuristic startswith match: QUESTION for {from_email} — '{body_clean}'")
                return {"intent": ResponseIntent.QUESTION, "sentiment": "neutral",
                        "urgency": "medium", "key_points": ["question"], "confidence": 0.90}

        # --- Conversation-ender heuristic ---
        if word_count <= ENDER_MAX_WORDS:
            if body_normalized in [re.sub(r'[^\w\s]', '', e).strip() for e in CONVERSATION_ENDERS]:
                return {"intent": ResponseIntent.CONVERSATION_COMPLETE, "sentiment": "positive",
                        "urgency": "low", "key_points": ["conversation_ender"], "confidence": 0.95}

        # --- Keyword-based fallback for interested/question ---
        # Catches messages that don't exactly match phrases but contain strong signals
        interested_keywords = ['yes', 'interested', 'sign me up', 'count me in', 'want in', "i'm in", 'please do']
        question_keywords = ['more info', 'more information', 'tell me more', 'how much', 'how does it work', 'what does it cost']
        if word_count <= HEURISTIC_MAX_WORDS:
            if any(kw in body_clean for kw in interested_keywords):
                logger.info(f"Keyword match: INTERESTED for {from_email} — '{body_clean}'")
                return {"intent": ResponseIntent.INTERESTED, "sentiment": "positive",
                        "urgency": "high", "key_points": ["interested"], "confidence": 0.85}
            if any(kw in body_clean for kw in question_keywords):
                logger.info(f"Keyword match: QUESTION for {from_email} — '{body_clean}'")
                return {"intent": ResponseIntent.QUESTION, "sentiment": "neutral",
                        "urgency": "medium", "key_points": ["question"], "confidence": 0.85}

        # AI-powered analysis for everything else (longer/complex messages)
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

    def generate_reply(self, email_data: Dict, analysis: Dict, inbox_email: str = '', lead_deadline: str = None) -> Optional[str]:
        """Generate a reply based on intent analysis. Uses inbox_email for brand context."""
        intent = analysis.get('intent', '')

        # Skip these — no reply needed
        if intent in [ResponseIntent.OUT_OF_OFFICE, ResponseIntent.SPAM, ResponseIntent.BOUNCE,
                       ResponseIntent.CONVERSATION_COMPLETE]:
            logger.info(f"Skipping reply for {intent}")
            return None

        # Determine brand for signoff
        _, brand_label = _get_brand_context(inbox_email)
        signoff = "RateTap Team" if 'ratetap' in (inbox_email or '').lower() else "Sarah, Wedding Counselors Directory"

        # Unsubscribe — quick template, no AI needed
        if intent == ResponseIntent.UNSUBSCRIBE:
            name = email_data.get('from_name', '').split()[0] if email_data.get('from_name') else 'there'
            return f"""Hi {name},

I've removed you from our mailing list. You won't receive any further emails from us.

Apologies for the inconvenience.

{signoff}"""

        # AI-generated reply for everything else
        system_prompt = _build_system_prompt(inbox_email)

        # Inject this lead's personal deadline so the AI uses the exact date
        # they were told in the outreach email — not any global/hardcoded date.
        if lead_deadline and 'ratetap' not in (inbox_email or '').lower():
            system_prompt += (
                f"\n\n## THIS LEAD'S PERSONAL DEADLINE\n"
                f"The founding member deadline for this specific person is **{lead_deadline}**. "
                f"Use this exact date in your reply. Do not use any other date."
            )

        prompt = REPLY_GENERATION_PROMPT.format(
            intent=intent,
            from_name=email_data.get('from_name', ''),
            from_email=email_data.get('from_email', ''),
            subject=email_data.get('subject', ''),
            body=email_data.get('body', '')
        )

        reply = self._call_ai(system_prompt, prompt, max_tokens=2048)
        if reply:
            logger.info(f"Generated reply for {email_data['from_email']} (intent: {intent})")
        return reply

    def should_auto_send(self, analysis: Dict) -> bool:
        """Determine if reply should be auto-sent.
        Always returns True when a reply was generated — never ghost a real person.
        Spam/OOO/bounce are already filtered out in generate_reply() (returns None).
        """
        return True


class AutoReplyScheduler:
    """Processes pending responses and sends AI replies."""

    def __init__(self, app=None, db=None):
        self.app = app
        self.db = db
        self.responder = AIResponder()

    # Max API failures (across runs) before escalating to human.
    # Each cron run = 1 retry attempt. At 6 retries with hourly cron,
    # the system tries for ~6 hours before giving up on a response.
    MAX_API_RETRIES = 6

    def process_pending_responses(self) -> int:
        """Process all unreviewed responses and send AI replies."""
        # EMERGENCY OVERRIDE: AI disabled by manager request
        logger.warning("AI Auto-responder DISABLED by manual override. Skipping all processing.")
        return 0

        from models import Response, Lead, SentEmail, Inbox
        from email_handler import EmailSender

        replies_sent = 0

        with self.app.app_context():
            pending = Response.query.filter_by(reviewed=False).all()
            logger.info(f"Found {len(pending)} unreviewed responses")

            for response in pending:
                try:
                    self.responder._last_error = None  # Reset for each response

                    lead = response.lead
                    if not lead:
                        response.reviewed = True
                        self.db.session.commit()
                        continue

                    # --- Guard: duplicate reply check ---
                    # If we already sent a reply after this response was received, skip
                    if response.received_at:
                        existing_reply = SentEmail.query.filter(
                            SentEmail.lead_id == lead.id,
                            SentEmail.subject.like('Re:%'),
                            SentEmail.sent_at >= response.received_at
                        ).first()
                        if existing_reply:
                            logger.info(f"Already replied to {lead.email} since their last response. Marking reviewed.")
                            response.reviewed = True
                            response.notes = "AI: duplicate — reply already sent"
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
                    confidence = analysis.get('confidence', 0)

                    # --- Guard: escalate unclear or low-confidence to human ---
                    if intent == ResponseIntent.UNCLEAR or confidence < 0.6:
                        logger.info(f"Low confidence ({confidence}) or unclear for {lead.email}. Escalating to human.")
                        response.reviewed = True
                        response.notified = True
                        response.notes = f"AI: {intent} (confidence={confidence:.0%}) — needs human review"
                        self.db.session.commit()
                        _notify_human_escalation(lead, f"Intent: {intent} (confidence: {confidence:.0%})\n\nSubject: {response.subject}\n\n{(response.body or '')[:500]}")
                        continue

                    # --- Conversation-complete: mark reviewed, no reply ---
                    if intent == ResponseIntent.CONVERSATION_COMPLETE:
                        response.reviewed = True
                        response.notified = True
                        response.notes = "AI: conversation complete — no reply needed"
                        self.db.session.commit()
                        logger.info(f"Conversation complete for {lead.email} — skipping reply")
                        continue

                    # Resolve inbox and campaign context BEFORE generating reply
                    # so we can pass brand context to the AI
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

                    # Generate reply with brand-appropriate context
                    inbox_email = inbox.email if inbox else ''
                    lead_deadline = getattr(lead, 'personal_deadline', None)
                    reply_text = self.responder.generate_reply(email_data, analysis, inbox_email=inbox_email, lead_deadline=lead_deadline)

                    if not reply_text:
                        # Only mark reviewed if this was an intentional skip (OOO/spam/bounce),
                        # NOT if the API failed (rate limit, error). Check if the AI
                        # actually decided to skip vs couldn't respond.
                        was_api_failure = getattr(self.responder, '_last_error', None)
                        if was_api_failure:
                            # Track retry count in notes to avoid infinite retries
                            retry_count = 0
                            if response.notes and response.notes.startswith("AI: api_retry="):
                                try:
                                    retry_count = int(response.notes.split("=")[1].split(" ")[0])
                                except (ValueError, IndexError):
                                    pass
                            retry_count += 1

                            if retry_count >= self.MAX_API_RETRIES:
                                logger.warning(f"Giving up on {lead.email} after {retry_count} API failures. Escalating to human.")
                                response.reviewed = True
                                response.notified = True
                                response.notes = f"AI: API failed {retry_count}x ({was_api_failure}) — needs human review"
                                self.db.session.commit()
                                _notify_human_escalation(lead, f"AI couldn't process after {retry_count} attempts ({was_api_failure}).\n\nSubject: {response.subject}\n\n{(response.body or '')[:500]}")
                            else:
                                response.notes = f"AI: api_retry={retry_count} ({was_api_failure})"
                                self.db.session.commit()
                                logger.warning(f"Skipping {lead.email} — API failure ({was_api_failure}), retry {retry_count}/{self.MAX_API_RETRIES}")

                            self.responder._last_error = None
                            continue

                        response.reviewed = True
                        response.notified = True
                        response.notes = f"AI: {intent} — no reply needed"
                        self.db.session.commit()
                        continue

                    # Send the reply (threaded into existing conversation)
                    sender = EmailSender(inbox)
                    original_subject = response.subject or "Your inquiry"
                    reply_subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"

                    # Build threading headers so reply appears in same thread
                    reply_to_id = None
                    ref_chain = None
                    if response.message_id:
                        reply_to_id = response.message_id
                        if not reply_to_id.startswith('<'):
                            reply_to_id = f'<{reply_to_id}>'
                    if sent_email and sent_email.message_id:
                        ref_chain = sent_email.message_id
                        if reply_to_id and reply_to_id != ref_chain:
                            ref_chain = f'{ref_chain} {reply_to_id}'
                    elif reply_to_id:
                        ref_chain = reply_to_id

                    # BCC owner so they can see AI replies in their inbox
                    bcc_email = os.getenv('NOTIFICATION_BCC_EMAIL')

                    success, message_id, error = sender.send_email(
                        to_email=lead.email,
                        subject=reply_subject,
                        body_html=reply_text.replace('\n', '<br>'),
                        bcc=bcc_email,
                        in_reply_to=reply_to_id,
                        references=ref_chain
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
                        confidence = analysis.get('confidence', 0)
                        _notify_auto_reply(lead, intent, reply_text, confidence)

                    else:
                        logger.error(f"Failed to send reply to {lead.email}: {error}")
                        response.reviewed = True
                        response.notified = True
                        response.notes = f"AI: {intent} — send FAILED: {error}"
                        self.db.session.commit()
                        _notify_failure(lead, f"Send failed to {lead.email}: {error}")

                except Exception as e:
                    logger.error(f"Error processing response {response.id}: {str(e)}")
                    self.db.session.rollback()
                    _notify_failure(lead if lead else None, str(e))
                    continue

        return replies_sent


def _notify_auto_reply(lead, intent, reply_text, confidence=1.0):
    """Send a Telegram notification when an AI reply is sent."""
    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return

        full_reply = reply_text[:3000].replace('<', '&lt;').replace('>', '&gt;')
        name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
        company = lead.company or ''

        confidence_tag = ""
        if confidence < 0.7:
            confidence_tag = f"\n⚠️ <b>LOW CONFIDENCE ({confidence:.0%}) — please verify</b>"

        header = f"✅ <b>Auto-Reply Sent</b>{confidence_tag}"
        who = f"→ {name}"
        if company:
            who += f" ({company})"
        who += f"\n📧 {lead.email}"

        msg = (
            f"{header}\n"
            f"{who}\n"
            f"🏷 {intent}\n\n"
            f"{full_reply}"
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Telegram notify failed: {e}")


def _notify_human_escalation(lead, reason):
    """Send Telegram notification when a response needs manual handling."""
    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return

        name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
        company = lead.company or ''
        reason_safe = reason[:1500].replace('<', '&lt;').replace('>', '&gt;')

        who = f"→ {name}"
        if company:
            who += f" ({company})"
        who += f"\n📧 {lead.email}"

        msg = (
            f"🔴 <b>Needs Your Reply</b>\n"
            f"{who}\n\n"
            f"{reason_safe}"
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Telegram escalation notify failed: {e}")


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
