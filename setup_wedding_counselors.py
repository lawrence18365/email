#!/usr/bin/env python3
"""
Setup script for Wedding Counselors Directory email outreach campaign.
Run once to set up inbox, campaign, and email sequences.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Inbox, Campaign, Sequence, Lead, CampaignLead

# === CONFIGURATION - UPDATE PASSWORD BELOW ===
EMAIL_PASSWORD = os.environ.get("WEDDING_EMAIL_PASSWORD", "")  # Set via environment variable
# =============================================

INBOX_CONFIG = {
    "name": "Wedding Counselors Main",
    "email": "hello@weddingcounselors.com",
    "smtp_host": "mail.spacemail.com",
    "smtp_port": 465,
    "smtp_use_tls": False,  # SSL uses False for use_tls, True means STARTTLS
    "imap_host": "mail.spacemail.com",
    "imap_port": 993,
    "imap_use_ssl": True,
    "username": "hello@weddingcounselors.com",
    "password": EMAIL_PASSWORD,
    "max_per_hour": 2,  # Targets ~16/day across a standard 9-17 window
    "active": True
}

# Email templates with personalization variables
# Psychology notes:
#   - "Free permanently" lands before $29/month mention (removes free-trial mental model)
#   - "No credit card, no catch" explicit in every email (removes #1 subconscious objection)
#   - Deadline framed as affecting NEW signups, not the recipient
#   - Endowment effect: "your spot", "yours stays free forever once you're in"
#   - "Reply yes" micro-commitment CTA added to emails 1 & 2 (lower friction than link-only)
#   - All under 80 words (2026 benchmark for cold email)
EMAIL_SEQUENCES = [
    {
        "step_number": 1,
        "delay_days": 0,
        "subject_template": "couple inquiry in {industry} — want in?",
        "email_template": """Hi {firstName|there},

I'm building WeddingCounselors.com — a directory dedicated to premarital counseling. We crossed 1,500 counselors this month and we're generating leads from couples in {industry} right now.

Founding member listings are free — permanently. No credit card, no catch. After {deadline}, new counselors pay $29/month. Yours stays free forever once you're in.

Takes 2 minutes: https://www.weddingcounselors.com/professional/signup

Or reply "yes" and I'll walk you through it.

Sarah
Wedding Counselors Directory"""
    },
    {
        "step_number": 2,
        "delay_days": 3,
        "subject_template": "re: couple inquiry in {industry}",
        "email_template": """Quick follow-up — founding members are already getting weekly visibility reports showing real profile views and couple inquiries from people searching in their area.

Your spot is still open. Free forever, no credit card. After {deadline}, new counselors pay $29/mo — that's for people who join after that date, not you once you're in.

2 minutes: https://www.weddingcounselors.com/professional/signup

Or reply "yes."

Sarah"""
    },
    {
        "step_number": 3,
        "delay_days": 5,
        "subject_template": "your free listing expires {deadline}",
        "email_template": """Hi {firstName|there},

Last note from me — after {deadline}, founding member listings close and new counselors pay $29/month.

Your listing is free permanently once you're in. I can't extend that to anyone who signs up after {deadline}.

Reply "yes" or sign up here: https://www.weddingcounselors.com/professional/signup

Sarah"""
    }
]


def setup():
    with app.app_context():
        print("Setting up Wedding Counselors outreach campaign...\n")

        # Check if inbox already exists
        existing_inbox = Inbox.query.filter_by(email=INBOX_CONFIG["email"]).first()
        if existing_inbox:
            print(f"Inbox {INBOX_CONFIG['email']} already exists (ID: {existing_inbox.id})")
            inbox = existing_inbox
            updated = False
            if inbox.max_per_hour != INBOX_CONFIG["max_per_hour"]:
                inbox.max_per_hour = INBOX_CONFIG["max_per_hour"]
                updated = True
            if updated:
                db.session.commit()
                print(f"Updated inbox settings for {inbox.email}")
        else:
            # Create inbox
            inbox = Inbox(**INBOX_CONFIG)
            db.session.add(inbox)
            db.session.commit()
            print(f"Created inbox: {inbox.email} (ID: {inbox.id})")

        # Check if campaign already exists
        existing_campaign = Campaign.query.filter_by(name="Wedding Counselors Outreach").first()
        if existing_campaign:
            print(f"Campaign already exists (ID: {existing_campaign.id})")
            campaign = existing_campaign
        else:
            # Create campaign
            campaign = Campaign(
                name="Wedding Counselors Outreach",
                inbox_id=inbox.id,
                status="draft"  # Start as draft, activate when ready
            )
            db.session.add(campaign)
            db.session.commit()
            print(f"Created campaign: {campaign.name} (ID: {campaign.id})")

        # Create sequences if they don't exist
        existing_sequences = Sequence.query.filter_by(campaign_id=campaign.id).all()
        existing_by_step = {seq.step_number: seq for seq in existing_sequences}
        created = 0
        updated = 0
        for seq_config in EMAIL_SEQUENCES:
            seq = existing_by_step.get(seq_config["step_number"])
            if seq:
                seq.delay_days = seq_config["delay_days"]
                seq.subject_template = seq_config["subject_template"]
                seq.email_template = seq_config["email_template"]
                seq.active = True
                updated += 1
            else:
                sequence = Sequence(
                    campaign_id=campaign.id,
                    **seq_config
                )
                db.session.add(sequence)
                created += 1
        if created or updated:
            db.session.commit()
        if updated:
            print(f"Updated {updated} existing email sequences")
        if created:
            print(f"Created {created} new email sequences")

        print("\n" + "="*50)
        print("SETUP COMPLETE!")
        print("="*50)
        print(f"\nInbox: {inbox.email}")
        print(f"Campaign: {campaign.name} (Status: {campaign.status})")
        print(f"Sequences: {len(EMAIL_SEQUENCES)} steps")
        print(f"  - Step 1: Immediate (day 0)")
        print(f"  - Step 2: Follow-up (day 7)")
        print(f"  - Step 3: Final (day 14)")
        print(f"\nSending rate: {inbox.max_per_hour} emails/hour")
        print(f"Daily estimate: ~10-15 emails (during business hours)")

        print("\n" + "="*50)
        print("NEXT STEPS:")
        print("="*50)
        print("1. Import your leads (CSV with: email, first_name, company)")
        print("2. Add leads to the campaign")
        print("3. Activate the campaign")
        print("4. Set up cron job for automation")
        print("\nRun the web UI: python app.py")
        print("Then visit: http://localhost:5001")


if __name__ == "__main__":
    if EMAIL_PASSWORD == "YOUR_PASSWORD_HERE":
        print("ERROR: Please edit this file and set your email password first!")
        print("Open setup_wedding_counselors.py and update EMAIL_PASSWORD")
        sys.exit(1)
    setup()
