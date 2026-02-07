from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailScheduler:
    """Background scheduler for email automation"""

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.scheduler = BackgroundScheduler(timezone=Config.TIMEZONE)

    def start(self):
        """Start the scheduler with all jobs"""
        logger.info("Starting email scheduler...")

        # Job 1: Send scheduled emails every hour
        self.scheduler.add_job(
            func=self._send_scheduled_emails_job,
            trigger=IntervalTrigger(minutes=Config.SEND_CHECK_INTERVAL_MINUTES),
            id='send_emails',
            name='Send scheduled emails',
            replace_existing=True
        )

        # Job 2: Check for responses every 10 minutes
        self.scheduler.add_job(
            func=self._check_responses_job,
            trigger=IntervalTrigger(minutes=Config.RESPONSE_CHECK_INTERVAL_MINUTES),
            id='check_responses',
            name='Check email responses',
            replace_existing=True
        )

        # Job 3: Cleanup old data daily at 2 AM
        self.scheduler.add_job(
            func=self._cleanup_job,
            trigger='cron',
            hour=2,
            minute=0,
            id='cleanup',
            name='Daily cleanup',
            replace_existing=True
        )

        # Job 4: AI Auto-reply to responses every 15 minutes
        self.scheduler.add_job(
            func=self._auto_reply_job,
            trigger=IntervalTrigger(minutes=15),
            id='auto_reply',
            name='AI auto-reply to responses',
            replace_existing=True
        )

        # Job 5: Lead prospecting every 6 hours (during business hours)
        self.scheduler.add_job(
            func=self._prospecting_job,
            trigger='cron',
            hour='9,15',  # Run at 9 AM and 3 PM
            minute=0,
            id='prospecting',
            name='AI lead prospecting',
            replace_existing=True
        )

        self.scheduler.start()
        logger.info("Scheduler started successfully (with autopilot features)")

    def shutdown(self):
        """Shutdown the scheduler"""
        logger.info("Shutting down scheduler...")
        self.scheduler.shutdown()

    def _send_scheduled_emails_job(self):
        """Job to send scheduled emails"""
        with self.app.app_context():
            try:
                logger.info("Running send_scheduled_emails job...")
                count = self.send_scheduled_emails()
                logger.info(f"Send job completed. Sent {count} emails.")
            except Exception as e:
                logger.error(f"Error in send_scheduled_emails job: {str(e)}")

    def _check_responses_job(self):
        """Job to check for email responses"""
        with self.app.app_context():
            try:
                logger.info("Running check_responses job...")
                count = self.check_responses()
                logger.info(f"Response check completed. Found {count} new responses.")
            except Exception as e:
                logger.error(f"Error in check_responses job: {str(e)}")

    def _auto_reply_job(self):
        """Job to auto-reply to responses using AI"""
        with self.app.app_context():
            try:
                logger.info("Running AI auto-reply job...")
                from ai_responder import AutoReplyScheduler
                responder = AutoReplyScheduler(self.app, self.db)
                count = responder.process_pending_responses()
                logger.info(f"Auto-reply job completed. Sent {count} AI-generated replies.")
            except Exception as e:
                logger.error(f"Error in auto_reply job: {str(e)}")

    def _prospecting_job(self):
        """Job to find new leads using AI"""
        with self.app.app_context():
            try:
                logger.info("Running AI prospecting job...")
                from lead_finder import LeadFinderScheduler
                finder = LeadFinderScheduler(self.app, self.db)
                result = finder.run_prospecting(limit=10, auto_add=True)
                logger.info(f"Prospecting job completed. Found {result['found']}, added {result['added']}.")
            except Exception as e:
                logger.error(f"Error in prospecting job: {str(e)}")

    def _cleanup_job(self):
        """Job to cleanup old data"""
        with self.app.app_context():
            try:
                logger.info("Running cleanup job...")
                self.cleanup_old_data()
                logger.info("Cleanup completed.")
            except Exception as e:
                logger.error(f"Error in cleanup job: {str(e)}")

    def send_scheduled_emails(self) -> int:
        """
        Send emails that are due to be sent

        Returns: number of emails sent
        """
        from models import Campaign, CampaignLead, Lead, Sequence, SentEmail, Inbox
        from email_handler import EmailSender, EmailPersonalizer, RateLimiter

        sent_count = 0
        now_local = datetime.now(ZoneInfo(Config.TIMEZONE))

        if self._should_pause_on_spike():
            paused = self._pause_all_campaigns()
            if paused:
                logger.warning("Paused all campaigns due to deliverability spike")
            return 0

        # Get all active campaigns
        active_campaigns = Campaign.query.filter_by(status='active').all()

        for campaign in active_campaigns:
            try:
                # Get campaign leads that are active
                campaign_leads = CampaignLead.query.filter_by(
                    campaign_id=campaign.id,
                    status='active'
                ).all()

                for campaign_lead in campaign_leads:
                    lead = campaign_lead.lead

                    # Skip if lead has responded
                    if lead.status in ('responded', 'meeting_booked', 'not_interested', 'unsubscribed'):
                        continue

                    # Find next sequence step to send
                    next_sequence = self._get_next_sequence_for_lead(lead.id, campaign.id)

                    if not next_sequence:
                        continue

                    # Check if it's time to send this sequence
                    if not self._is_sequence_due(lead.id, campaign.id, next_sequence):
                        continue

                    selected_inbox, max_per_hour = self._select_inbox_for_campaign(campaign, now_local)
                    if not selected_inbox:
                        continue

                    # Verify email before sending (Verifalia - 25 free/day)
                    from email_verifier import EmailVerifier
                    verifier = EmailVerifier(self.db.session)
                    verification_status = verifier.verify_email(lead)
                    if not verifier.should_send(verification_status):
                        logger.warning(f"Skipping {lead.email}: verification={verification_status}")
                        campaign_lead.status = 'stopped'
                        self.db.session.commit()
                        continue

                    # Send the email
                    success = self._send_sequence_email(lead, campaign, next_sequence, selected_inbox)

                    if success:
                        sent_count += 1

                        # Update lead status
                        if lead.status == 'new':
                            lead.status = 'contacted'
                            self.db.session.commit()

            except Exception as e:
                logger.error(f"Error processing campaign {campaign.id}: {str(e)}")
                continue

        return sent_count

    def _should_pause_on_spike(self) -> bool:
        """Detect recent bounce/failure spikes."""
        from models import SentEmail

        window_start = datetime.utcnow() - timedelta(minutes=Config.SPIKE_WINDOW_MINUTES)
        total_sent = SentEmail.query.filter(
            SentEmail.sent_at >= window_start,
            SentEmail.status == 'sent'
        ).count()

        if total_sent == 0:
            return False

        bounced = SentEmail.query.filter(
            SentEmail.sent_at >= window_start,
            SentEmail.status == 'bounced'
        ).count()

        failed = SentEmail.query.filter(
            SentEmail.sent_at >= window_start,
            SentEmail.status == 'failed'
        ).count()

        bounce_rate = bounced / total_sent * 100
        failure_rate = failed / total_sent * 100

        return bounce_rate >= Config.SPIKE_BOUNCE_RATE or failure_rate >= Config.SPIKE_FAILURE_RATE

    def _pause_all_campaigns(self) -> bool:
        """Pause all active campaigns."""
        from models import Campaign

        active = Campaign.query.filter_by(status='active').all()
        if not active:
            return False

        for campaign in active:
            campaign.status = 'paused'
        self.db.session.commit()
        return True

    def _get_inbox_schedule_limit(self, inbox, now_local: datetime) -> tuple[bool, int]:
        """Return whether inbox can send now and the max_per_hour to use."""
        from models import SendingSchedule

        schedules = SendingSchedule.query.filter_by(inbox_id=inbox.id).all()
        if schedules:
            hour_row = next((s for s in schedules if s.hour_of_day == now_local.hour), None)
            if not hour_row or not hour_row.active:
                return False, inbox.max_per_hour
            return True, hour_row.max_per_hour or inbox.max_per_hour

        within_window = Config.DEFAULT_SENDING_HOURS_START <= now_local.hour < Config.DEFAULT_SENDING_HOURS_END
        return within_window, inbox.max_per_hour

    def _get_rotation_pool_inboxes(self, campaign):
        """Return the ordered inbox pool for rotation."""
        from models import Inbox

        if campaign.rotation_inboxes:
            inbox_ids = [ci.inbox_id for ci in campaign.rotation_inboxes]
            inboxes = Inbox.query.filter(Inbox.id.in_(inbox_ids), Inbox.active == True).all()
        else:
            inboxes = [campaign.inbox] if campaign.inbox and campaign.inbox.active else []

        return sorted(inboxes, key=lambda i: i.id)

    def _select_inbox_for_campaign(self, campaign, now_local: datetime):
        """Pick an inbox using rotation + schedule + rate limits."""
        from models import SentEmail
        from email_handler import RateLimiter

        inboxes = self._get_rotation_pool_inboxes(campaign)
        if not inboxes:
            return None, None

        last_sent = SentEmail.query.filter_by(
            campaign_id=campaign.id,
            status='sent'
        ).order_by(SentEmail.sent_at.desc()).first()

        start_index = 0
        if last_sent:
            for idx, inbox in enumerate(inboxes):
                if inbox.id == last_sent.inbox_id:
                    start_index = (idx + 1) % len(inboxes)
                    break

        ordered = inboxes[start_index:] + inboxes[:start_index]
        rate_limiter = RateLimiter(self.db.session)

        for inbox in ordered:
            within_window, max_per_hour = self._get_inbox_schedule_limit(inbox, now_local)
            if not within_window:
                continue
            if not rate_limiter.can_send(inbox.id, max_per_hour):
                logger.info(f"Rate limit reached for inbox {inbox.email}")
                continue
            return inbox, max_per_hour

        return None, None

    def _get_next_sequence_for_lead(self, lead_id: int, campaign_id: int):
        """Get the next sequence step that should be sent to this lead"""
        from models import Sequence, SentEmail

        # Get all sequences for this campaign, ordered by step
        sequences = Sequence.query.filter_by(
            campaign_id=campaign_id,
            active=True
        ).order_by(Sequence.step_number).all()

        if not sequences:
            return None

        # Get all sent emails for this lead in this campaign
        sent_steps = self.db.session.query(SentEmail.sequence_id).filter_by(
            lead_id=lead_id,
            campaign_id=campaign_id,
            status='sent'
        ).all()

        sent_sequence_ids = [s[0] for s in sent_steps]

        # Find first sequence not yet sent
        for sequence in sequences:
            if sequence.id not in sent_sequence_ids:
                return sequence

        return None

    def _is_sequence_due(self, lead_id: int, campaign_id: int, sequence) -> bool:
        """Check if this sequence step is due to be sent"""
        from models import SentEmail

        # If it's the first step (delay_days = 0), it's always due
        if sequence.step_number == 1:
            return True

        # Get the last sent email in this campaign for this lead
        last_sent = SentEmail.query.filter_by(
            lead_id=lead_id,
            campaign_id=campaign_id,
            status='sent'
        ).order_by(SentEmail.sent_at.desc()).first()

        if not last_sent:
            # No previous email, so first step is due
            return sequence.step_number == 1

        # Check if enough days have passed
        days_since_last = (datetime.utcnow() - last_sent.sent_at).days

        return days_since_last >= sequence.delay_days

    def _send_sequence_email(self, lead, campaign, sequence, inbox) -> bool:
        """Send a specific sequence email to a lead"""
        from models import SentEmail
        from email_handler import EmailSender, EmailPersonalizer
        from email_templates import wrap_email_html

        try:
            # Personalize subject and body
            subject = EmailPersonalizer.personalize(sequence.subject_template, lead)
            body = EmailPersonalizer.personalize(sequence.email_template, lead)

            # Wrap in professional HTML template with staff signature
            body_html = wrap_email_html(body, inbox.email, lead=lead)

            # Send email
            sender = EmailSender(inbox)
            success, message_id, error = sender.send_email(
                to_email=lead.email,
                subject=subject,
                body_html=body_html
            )

            # Record sent email
            sent_email = SentEmail(
                lead_id=lead.id,
                campaign_id=campaign.id,
                sequence_id=sequence.id,
                inbox_id=inbox.id,
                message_id=message_id if success else None,
                subject=subject,
                body=body,
                status='sent' if success else 'failed',
                error_message=error,
                sent_at=datetime.utcnow()
            )

            self.db.session.add(sent_email)
            self.db.session.commit()

            if success:
                logger.info(f"Sent email to {lead.email} (Campaign: {campaign.name}, Step: {sequence.step_number}, Inbox: {inbox.email})")
            else:
                logger.error(f"Failed to send to {lead.email}: {error}")

            return success

        except Exception as e:
            logger.error(f"Error sending email to {lead.email}: {str(e)}")
            self.db.session.rollback()
            return False

    def check_responses(self) -> int:
        """
        Check all inboxes for new responses

        Returns: number of new responses found
        """
        from models import Inbox, Response, SentEmail, Lead
        from email_handler import EmailReceiver

        response_count = 0

        # Get all active inboxes
        inboxes = Inbox.query.filter_by(active=True).all()

        for inbox in inboxes:
            try:
                receiver = EmailReceiver(inbox)
                responses = receiver.fetch_new_responses()

                for resp in responses:
                    if self._is_bounce_message(resp):
                        sent_email = self._match_bounce_to_sent_email(resp)
                        if sent_email and sent_email.status != 'bounced':
                            sent_email.status = 'bounced'
                            sent_email.error_message = 'Bounce detected from inbox'
                            self.db.session.commit()
                            logger.warning(f"Marked bounced email for {sent_email.lead.email}")
                        continue

                    # Try to match response to sent email
                    sent_email = None

                    if resp['in_reply_to']:
                        sent_email = SentEmail.query.filter_by(
                            message_id=resp['in_reply_to']
                        ).first()

                    # If not found by In-Reply-To, try References header
                    if not sent_email and resp['references']:
                        ref_ids = resp['references'].split()
                        for ref_id in ref_ids:
                            ref_id = ref_id.strip('<>')
                            sent_email = SentEmail.query.filter_by(
                                message_id=ref_id
                            ).first()
                            if sent_email:
                                break

                    # Extract email address from 'From' header
                    from_email = self._extract_email(resp['from'])

                    # Find lead by email
                    lead = Lead.query.filter_by(email=from_email).first()

                    if not lead and sent_email:
                        lead = sent_email.lead

                    if lead:
                        label = self._auto_label_response(resp)

                        # Save response
                        response = Response(
                            lead_id=lead.id,
                            sent_email_id=sent_email.id if sent_email else None,
                            message_id=resp['message_id'],
                            in_reply_to=resp['in_reply_to'],
                            subject=resp['subject'],
                            body=resp['body'],
                            received_at=resp['date'],
                            label=label
                        )

                        self.db.session.add(response)

                        # Update lead status
                        if label == 'unsubscribe':
                            lead.status = 'not_interested'
                        elif lead.status != 'meeting_booked':
                            lead.status = 'responded'

                        # Stop further sequences for this lead in all campaigns
                        from models import CampaignLead
                        campaign_leads = CampaignLead.query.filter_by(lead_id=lead.id).all()
                        for cl in campaign_leads:
                            if cl.status == 'active':
                                cl.status = 'completed'

                        self.db.session.commit()
                        response_count += 1

                        logger.info(f"Recorded response from {lead.email}")

            except Exception as e:
                logger.error(f"Error checking responses for inbox {inbox.email}: {str(e)}")
                self.db.session.rollback()
                continue

        return response_count

    def _auto_label_response(self, resp: dict) -> 'str | None':
        """Apply a simple label based on common keywords."""
        subject = (resp.get('subject') or '').lower()
        body = (resp.get('body') or '').lower()

        if "out of office" in subject or "out of office" in body:
            return "out_of_office"
        if "unsubscribe" in body or "remove me" in body or "opt out" in body:
            return "unsubscribe"
        if "wrong person" in body or "not the right person" in body:
            return "wrong_contact"

        return None

    def _is_bounce_message(self, resp: dict) -> bool:
        """Heuristic bounce detection based on sender/subject/body."""
        from_header = (resp.get('from') or '').lower()
        subject = (resp.get('subject') or '').lower()
        body = (resp.get('body') or '').lower()

        bounce_senders = ('mailer-daemon', 'postmaster', 'mail delivery subsystem')
        bounce_subjects = (
            'undeliverable',
            'delivery status notification',
            'mail delivery failed',
            'delivery failure',
            'returned mail',
            'failure notice',
            'undelivered mail'
        )

        if any(s in from_header for s in bounce_senders):
            return True
        if any(s in subject for s in bounce_subjects):
            return True
        if 'diagnostic-code' in body and 'delivery' in body:
            return True

        return False

    def _match_bounce_to_sent_email(self, resp: dict):
        """Match a bounce to a SentEmail via headers or references."""
        from models import SentEmail

        if resp.get('in_reply_to'):
            sent_email = SentEmail.query.filter_by(message_id=resp['in_reply_to']).first()
            if sent_email:
                return sent_email

        references = resp.get('references') or ''
        for ref_id in references.split():
            ref_id = ref_id.strip('<>')
            sent_email = SentEmail.query.filter_by(message_id=ref_id).first()
            if sent_email:
                return sent_email

        return None

    def _extract_email(self, from_header: str) -> str:
        """Extract email address from From header"""
        import re
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
        return match.group(0) if match else from_header

    def cleanup_old_data(self):
        """Cleanup old data (optional - implement as needed)"""
        # Could delete old sent emails, responses, etc.
        # For now, just log
        logger.info("Cleanup job executed (no cleanup implemented yet)")
        pass
