#!/usr/bin/env python3
"""
PRE-VERIFY EMAILS — Nightly batch job to pre-verify tomorrow's send queue.

Verifalia free tier = 25 verifications/day. The daily send cap is 50.
Running verification overnight ensures the daytime send loop doesn't waste
quota on leads that turn out to be undeliverable.

Priority order:
1. Leads scheduled for step 1 (never contacted) — highest risk of bad email
2. Leads with the shortest delay_days remaining
3. Oldest unverified leads

Run:  python preverify_emails.py
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
from models import db, Lead, CampaignLead, Campaign, Sequence, SentEmail
from email_verifier import EmailVerifier


def get_next_send_queue():
    """Get leads likely to be sent tomorrow, ordered by priority."""
    candidates = []

    active_campaigns = Campaign.query.filter_by(status='active').all()

    for campaign in active_campaigns:
        campaign_leads = CampaignLead.query.filter_by(
            campaign_id=campaign.id,
            status='active'
        ).all()

        for cl in campaign_leads:
            lead = cl.lead
            if not lead or lead.status in ('responded', 'signed_up', 'bounced', 'not_interested', 'complained'):
                continue

            # Already verified and deliverable — skip
            if lead.email_verified and lead.email_verification_status == 'Deliverable':
                continue
            # Already marked undeliverable — skip
            if lead.email_verification_status in ('Undeliverable', 'Risky'):
                continue

            # Figure out which step is next
            last_sent = SentEmail.query.filter_by(
                lead_id=lead.id,
                campaign_id=campaign.id
            ).order_by(SentEmail.sent_at.desc()).first()

            if last_sent:
                next_step = last_sent.sequence.step_number + 1
                next_seq = Sequence.query.filter_by(
                    campaign_id=campaign.id,
                    step_number=next_step,
                    active=True
                ).first()
                if not next_seq:
                    continue
                # Check if delay has elapsed (or will elapse by tomorrow)
                ready_at = last_sent.sent_at + timedelta(days=next_seq.delay_days)
                if ready_at > datetime.utcnow() + timedelta(days=1):
                    continue
                priority = next_step  # Higher step = lower priority
            else:
                priority = 0  # Step 1 = highest priority (never contacted, most likely bad)

            candidates.append((priority, lead))

    # Sort: step 1 first, then by step number
    candidates.sort(key=lambda c: c[0])
    return [lead for _, lead in candidates]


def run_preverification():
    """Pre-verify up to 25 emails from tomorrow's send queue."""
    logger.info("Starting nightly pre-verification...")

    with app.app_context():
        verifier = EmailVerifier(db.session)

        if not verifier._has_credentials():
            logger.warning("Verifalia credentials not configured. Skipping.")
            return 0

        queue = get_next_send_queue()
        logger.info(f"Found {len(queue)} unverified leads in tomorrow's send queue")

        verified = 0
        blocked = 0

        for lead in queue[:25]:  # Verifalia free tier = 25/day
            if not verifier._has_quota_remaining():
                logger.info("Verifalia quota exhausted for today.")
                break

            status = verifier.verify_email(lead)
            verified += 1

            if status in ('Undeliverable', 'Risky'):
                blocked += 1
                logger.info(f"BLOCKED: {lead.email} -> {status}")
            else:
                logger.info(f"OK: {lead.email} -> {status}")

        logger.info(f"Pre-verification complete: {verified} verified, {blocked} blocked")
        return verified


if __name__ == "__main__":
    run_preverification()
