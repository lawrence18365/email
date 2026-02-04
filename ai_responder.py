"""
AI Email Responder - Fully Autonomous Reply System

Reads incoming emails, understands intent, drafts personalized replies,
and sends them automatically like a human assistant.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Anthropic client
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Response categories
class ResponseIntent:
    INTERESTED = "interested"  # Wants to learn more, schedule call
    MEETING_REQUEST = "meeting_request"  # Explicitly asks for meeting
    QUESTION = "question"  # Has specific questions
    NOT_INTERESTED = "not_interested"  # Polite decline
    UNSUBSCRIBE = "unsubscribe"  # Wants to be removed
    OUT_OF_OFFICE = "out_of_office"  # Auto-reply, OOO
    SPAM = "spam"  # Irrelevant/spam response
    UNCLEAR = "unclear"  # Can't determine intent


INTENT_ANALYSIS_PROMPT = """Analyze this email response and determine the sender's intent.

Email from: {from_name} ({from_email})
Company: {company}
Subject: {subject}

Email body:
{body}

---
Original outreach context:
We reached out about Wedding Counselors Directory (weddingcounselors.com).

Classify the intent as ONE of:
- interested: They want to learn more or seem open to conversation
- meeting_request: They explicitly want to schedule a meeting/call
- question: They have specific questions about our offering
- not_interested: They politely declined or said not now
- unsubscribe: They want to be removed from emails
- out_of_office: This is an auto-reply or out of office message
- spam: Irrelevant response or spam
- unclear: Can't determine their intent

Also extract:
- sentiment: positive, neutral, negative
- urgency: high, medium, low
- key_points: List of main points they mentioned

Respond in JSON format:
{{
    "intent": "category",
    "sentiment": "positive/neutral/negative",
    "urgency": "high/medium/low",
    "key_points": ["point1", "point2"],
    "suggested_action": "brief suggestion",
    "confidence": 0.0-1.0
}}
"""

REPLY_GENERATION_PROMPT = """You are a friendly, professional sales assistant for Wedding Counselors Directory.

Generate a personalized email reply to this lead.

Lead info:
- Name: {first_name} {last_name}
- Company: {company}
- Email: {email}

Their message:
Subject: {subject}
{body}

Analysis:
- Intent: {intent}
- Sentiment: {sentiment}
- Key points: {key_points}

Our previous outreach:
{previous_email}

---

Guidelines:
1. Be warm, professional, and conversational (not salesy)
2. Address their specific points/questions directly
3. Keep it concise (3-5 short paragraphs max)
4. If they're interested: propose next steps (call/demo)
5. If they have questions: answer them helpfully
6. If not interested: thank them graciously, leave door open
7. Include a clear call-to-action when appropriate
8. Sign off as "Best regards, Wedding Counselors Directory Team"

DO NOT:
- Be pushy or aggressive
- Use excessive exclamation marks
- Include generic filler phrases
- Make up information about our product

Respond with ONLY the email body (no subject line, no JSON, just the reply text).
"""

CALENDLY_LINK = os.getenv('CALENDLY_LINK', '')


class AIResponder:
    """AI-powered email response system"""

    def __init__(self, db_session=None):
        self.db = db_session

    def analyze_intent(self, email_data: Dict) -> Dict:
        """
        Analyze the intent of an incoming email

        Args:
            email_data: Dict with keys: from_name, from_email, company, subject, body

        Returns:
            Dict with intent analysis
        """
        prompt = INTENT_ANALYSIS_PROMPT.format(**email_data)

        try:
            response = anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            result_text = response.content[0].text

            # Parse JSON response
            # Find JSON in response (handle markdown code blocks)
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                analysis = {
                    "intent": ResponseIntent.UNCLEAR,
                    "sentiment": "neutral",
                    "urgency": "medium",
                    "key_points": [],
                    "suggested_action": "Manual review needed",
                    "confidence": 0.5
                }

            logger.info(f"Analyzed email from {email_data['from_email']}: intent={analysis['intent']}")
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing intent: {str(e)}")
            return {
                "intent": ResponseIntent.UNCLEAR,
                "sentiment": "neutral",
                "urgency": "medium",
                "key_points": [],
                "suggested_action": f"Error: {str(e)}",
                "confidence": 0.0
            }

    def generate_reply(self, lead_data: Dict, email_data: Dict,
                       analysis: Dict, previous_email: str = "") -> str:
        """
        Generate a personalized reply based on intent analysis

        Args:
            lead_data: Dict with lead info (first_name, last_name, company, email)
            email_data: Dict with email info (subject, body)
            analysis: Intent analysis from analyze_intent()
            previous_email: Our previous email for context

        Returns:
            Generated reply text
        """
        # Handle special cases
        if analysis['intent'] == ResponseIntent.OUT_OF_OFFICE:
            logger.info("Out of office detected - skipping reply")
            return None

        if analysis['intent'] == ResponseIntent.SPAM:
            logger.info("Spam detected - skipping reply")
            return None

        if analysis['intent'] == ResponseIntent.UNSUBSCRIBE:
            return self._generate_unsubscribe_reply(lead_data)

        # Generate personalized reply
        prompt_data = {
            **lead_data,
            **email_data,
            "intent": analysis['intent'],
            "sentiment": analysis['sentiment'],
            "key_points": ", ".join(analysis.get('key_points', [])),
            "previous_email": previous_email or "(Initial outreach about Wedding Counselors Directory)"
        }

        prompt = REPLY_GENERATION_PROMPT.format(**prompt_data)

        try:
            response = anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )

            reply = response.content[0].text.strip()

            # Add meeting link if they're interested
            if analysis['intent'] in [ResponseIntent.INTERESTED, ResponseIntent.MEETING_REQUEST]:
                if CALENDLY_LINK and CALENDLY_LINK not in reply:
                    reply += f"\n\nFeel free to book a time that works for you: {CALENDLY_LINK}"

            logger.info(f"Generated reply for {lead_data['email']} (intent: {analysis['intent']})")
            return reply

        except Exception as e:
            logger.error(f"Error generating reply: {str(e)}")
            return None

    def _generate_unsubscribe_reply(self, lead_data: Dict) -> str:
        """Generate a polite unsubscribe confirmation"""
        return f"""Hi {lead_data.get('first_name', 'there')},

Thank you for letting us know. I've removed you from our mailing list and you won't receive any further emails from us.

If you ever change your mind or have questions in the future, feel free to reach out.

Best regards,
Wedding Counselors Directory Team"""

    def process_response(self, response_record, lead, sent_email=None) -> Tuple[str, Dict]:
        """
        Process a response record and generate appropriate reply

        Args:
            response_record: Response model instance
            lead: Lead model instance
            sent_email: Optional SentEmail model instance (our previous email)

        Returns:
            Tuple of (reply_text, analysis_dict)
        """
        # Prepare data
        email_data = {
            "from_name": lead.full_name,
            "from_email": lead.email,
            "company": lead.company or "Unknown",
            "subject": response_record.subject or "",
            "body": response_record.body or ""
        }

        lead_data = {
            "first_name": lead.first_name or "there",
            "last_name": lead.last_name or "",
            "company": lead.company or "",
            "email": lead.email
        }

        previous_email = ""
        if sent_email:
            previous_email = f"Subject: {sent_email.subject}\n\n{sent_email.body}"

        # Analyze intent
        analysis = self.analyze_intent(email_data)

        # Generate reply
        reply = self.generate_reply(lead_data, email_data, analysis, previous_email)

        return reply, analysis

    def should_auto_send(self, analysis: Dict) -> bool:
        """
        Determine if reply should be auto-sent based on analysis

        Returns True for most cases (full autopilot mode)
        """
        # Always auto-send unless confidence is very low
        if analysis.get('confidence', 0) < 0.5:
            return False

        # Skip spam and out of office
        if analysis['intent'] in [ResponseIntent.SPAM, ResponseIntent.OUT_OF_OFFICE]:
            return False

        # Auto-send everything else
        return True


class AutoReplyScheduler:
    """Scheduler for automatic email replies"""

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.responder = AIResponder()

    def process_pending_responses(self) -> int:
        """
        Process all unprocessed responses and send replies

        Returns: Number of replies sent
        """
        from models import Response, Lead, SentEmail, Inbox
        from email_handler import EmailSender

        replies_sent = 0

        with self.app.app_context():
            # Get unprocessed responses (not reviewed yet)
            pending = Response.query.filter_by(reviewed=False).all()

            for response in pending:
                try:
                    lead = response.lead
                    sent_email = response.sent_email

                    # Skip if no lead
                    if not lead:
                        continue

                    # Process and generate reply
                    reply_text, analysis = self.responder.process_response(
                        response, lead, sent_email
                    )

                    # Skip if no reply generated
                    if not reply_text:
                        response.reviewed = True
                        response.notes = f"AI analysis: {analysis['intent']} - No reply needed"
                        self.db.session.commit()
                        continue

                    # Check if should auto-send
                    if not self.responder.should_auto_send(analysis):
                        response.notes = f"AI draft (needs review): {reply_text[:200]}..."
                        self.db.session.commit()
                        logger.info(f"Reply queued for review: {lead.email}")
                        continue

                    # Get inbox to send from (use same as original email or first active)
                    inbox = None
                    if sent_email and sent_email.inbox:
                        inbox = sent_email.inbox
                    else:
                        inbox = Inbox.query.filter_by(active=True).first()

                    if not inbox:
                        logger.error("No active inbox found for sending reply")
                        continue

                    # Send the reply
                    sender = EmailSender(inbox)

                    # Create reply subject
                    original_subject = response.subject or "Your inquiry"
                    if not original_subject.lower().startswith("re:"):
                        reply_subject = f"Re: {original_subject}"
                    else:
                        reply_subject = original_subject

                    success, message_id, error = sender.send_email(
                        to_email=lead.email,
                        subject=reply_subject,
                        body_html=reply_text.replace('\n', '<br>')
                    )

                    if success:
                        # Record sent reply
                        reply_record = SentEmail(
                            lead_id=lead.id,
                            campaign_id=sent_email.campaign_id if sent_email else None,
                            sequence_id=sent_email.sequence_id if sent_email else None,
                            inbox_id=inbox.id,
                            message_id=message_id,
                            subject=reply_subject,
                            body=reply_text,
                            status='sent'
                        )
                        self.db.session.add(reply_record)

                        # Mark response as reviewed
                        response.reviewed = True
                        response.notes = f"AI auto-replied ({analysis['intent']})"

                        # Update lead status based on intent
                        if analysis['intent'] == ResponseIntent.MEETING_REQUEST:
                            lead.status = 'meeting_booked'
                        elif analysis['intent'] == ResponseIntent.NOT_INTERESTED:
                            lead.status = 'not_interested'
                        elif analysis['intent'] == ResponseIntent.UNSUBSCRIBE:
                            lead.status = 'not_interested'

                        self.db.session.commit()
                        replies_sent += 1

                        logger.info(f"Auto-replied to {lead.email} (intent: {analysis['intent']})")

                    else:
                        logger.error(f"Failed to send reply to {lead.email}: {error}")

                except Exception as e:
                    logger.error(f"Error processing response {response.id}: {str(e)}")
                    self.db.session.rollback()
                    continue

        return replies_sent
