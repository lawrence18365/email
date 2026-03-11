#!/usr/bin/env python3
"""
Re-engage completed leads — Add step 5 to Campaign A and reactivate
leads who completed all 4 steps without responding.

These 353 leads received all 4 emails and never replied. This script:
1. Adds a new step 5 with a completely different angle (social proof + fresh CTA)
2. Reactivates completed CampaignLead records so the cron picks them up
3. Only reactivates leads who are NOT responded/signed_up/bounced/complained

SAFE: Skips leads who already have step 5 sent. Idempotent.

Run via: GitHub Actions → "Update WC Sequences" workflow_dispatch
         python reengage_completed_leads.py --dry-run   # Preview
         python reengage_completed_leads.py              # Apply
"""

import os
import sys
import argparse
import logging
from datetime import datetime

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app import app
from models import db, Campaign, Sequence, CampaignLead, Lead, SentEmail, Suppression

# ─── Step 5: The "Results" Email ────────────────────────────────────────────
# Completely different angle from steps 1-4. Instead of pitching the offer,
# lead with a concrete result another counselor got. Short, casual, low-pressure.
# Uses the "social proof + curiosity" approach that outperforms urgency/scarcity
# on re-engagement sends.

STEP5_SUBJECT = "one of our counselors just got 3 couple inquiries"
STEP5_DELAY = 14  # 14 days after step 4 = ~5 weeks after first email

STEP5_BODY = (
    "Hi {firstName|there},\n\n"
    "Quick update — one of our founding members in {industry} just told me "
    "she got 3 couple inquiries through her profile last month. She said "
    "she wasn't expecting much when she signed up, but the couples found "
    "her through Google and reached out directly.\n\n"
    "Thought of you because your area still has very few counselors listed. "
    "Couples searching there right now are finding generic directories "
    "instead of specialists like you.\n\n"
    "Your founding member spot is still open if you want it — free permanently, "
    "takes 2 minutes:\n"
    "https://www.weddingcounselors.com/professional/signup"
    "?utm_source=email&utm_medium=outreach&utm_campaign=reengage\n\n"
    "No pressure either way.\n\n"
    "Sarah"
)


def main():
    parser = argparse.ArgumentParser(description="Re-engage completed leads with step 5")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    args = parser.parse_args()

    with app.app_context():
        campaign = Campaign.query.get(1)
        if not campaign:
            print("ERROR: Campaign ID=1 not found")
            sys.exit(1)

        print(f"Campaign: {campaign.name} (ID={campaign.id})")

        # ── Step 1: Add step 5 sequence ──────────────────────────────────
        existing_step5 = Sequence.query.filter_by(
            campaign_id=campaign.id,
            step_number=5
        ).first()

        if existing_step5:
            # Update if content changed
            changed = (
                existing_step5.subject_template != STEP5_SUBJECT or
                existing_step5.email_template != STEP5_BODY or
                existing_step5.delay_days != STEP5_DELAY
            )
            if changed and not args.dry_run:
                existing_step5.subject_template = STEP5_SUBJECT
                existing_step5.email_template = STEP5_BODY
                existing_step5.delay_days = STEP5_DELAY
                existing_step5.active = True
                db.session.commit()
                print(f"  Step 5: UPDATED")
            elif changed:
                print(f"  Step 5: [DRY RUN] would update")
            else:
                print(f"  Step 5: OK (already exists, no changes)")
        else:
            if args.dry_run:
                print(f"  Step 5: [DRY RUN] would create — subject: {STEP5_SUBJECT!r}")
            else:
                seq = Sequence(
                    campaign_id=campaign.id,
                    step_number=5,
                    delay_days=STEP5_DELAY,
                    subject_template=STEP5_SUBJECT,
                    email_template=STEP5_BODY,
                    active=True,
                )
                db.session.add(seq)
                db.session.commit()
                print(f"  Step 5: CREATED — subject: {STEP5_SUBJECT!r}")

        # ── Step 2: Find completed leads eligible for re-engagement ──────
        completed_cls = CampaignLead.query.filter_by(
            campaign_id=campaign.id,
            status='completed'
        ).all()

        print(f"\nCompleted leads in campaign: {len(completed_cls)}")

        # Get suppression list
        suppressed_emails = {s.email.lower() for s in Suppression.query.all()}

        # Check step 5 sequence ID for dedup
        step5_seq = Sequence.query.filter_by(
            campaign_id=campaign.id,
            step_number=5,
            active=True
        ).first()

        reactivate = []
        skip_responded = 0
        skip_signed_up = 0
        skip_bounced = 0
        skip_suppressed = 0
        skip_already_sent = 0

        for cl in completed_cls:
            lead = Lead.query.get(cl.lead_id)
            if not lead:
                continue

            # Skip leads in terminal states
            if lead.status in ('responded', 'meeting_booked'):
                skip_responded += 1
                continue
            if lead.status == 'signed_up':
                skip_signed_up += 1
                continue
            if lead.status in ('bounced', 'complained', 'not_interested'):
                skip_bounced += 1
                continue
            if lead.email.lower() in suppressed_emails:
                skip_suppressed += 1
                continue

            # Skip if step 5 already sent
            if step5_seq:
                already = SentEmail.query.filter_by(
                    lead_id=lead.id,
                    campaign_id=campaign.id,
                    sequence_id=step5_seq.id,
                    status='sent'
                ).first()
                if already:
                    skip_already_sent += 1
                    continue

            reactivate.append(cl)

        print(f"\nEligible for re-engagement: {len(reactivate)}")
        print(f"  Skipped (responded):    {skip_responded}")
        print(f"  Skipped (signed up):    {skip_signed_up}")
        print(f"  Skipped (bounced/etc):  {skip_bounced}")
        print(f"  Skipped (suppressed):   {skip_suppressed}")
        print(f"  Skipped (step 5 sent):  {skip_already_sent}")

        if args.dry_run:
            print(f"\n[DRY RUN] Would reactivate {len(reactivate)} leads for step 5")
            if reactivate:
                # Show first 10 as preview
                for cl in reactivate[:10]:
                    lead = Lead.query.get(cl.lead_id)
                    print(f"  {lead.email} (status: {lead.status})")
                if len(reactivate) > 10:
                    print(f"  ...and {len(reactivate) - 10} more")
        else:
            count = 0
            for cl in reactivate:
                cl.status = 'active'
                count += 1

            db.session.commit()
            print(f"\nReactivated {count} leads for step 5 delivery")

        print("\nDone.")


if __name__ == "__main__":
    main()
