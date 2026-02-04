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
EMAIL_SEQUENCES = [
    {
        "step_number": 1,
        "delay_days": 0,  # Send immediately when added to campaign
        "subject_template": "About {company} on Wedding Counselors Directory",
        "email_template": """Hi {firstName},

I lead partnerships at Wedding Counselors Directory. We are building a trusted directory for premarital counselors and clergy.

We would like to include {company} with a complimentary founding listing (profile, services, and contact info). Setup takes about 2 minutes.

Open to it? Reply "yes" and I will send the link.

Best,
Wedding Counselors Directory Team
https://weddingcounselors.com"""
    },
    {
        "step_number": 2,
        "delay_days": 3,  # 3 days after first email
        "subject_template": "Quick follow-up on your directory listing",
        "email_template": """Hi {firstName},

Quick follow-up on the Wedding Counselors Directory listing for {company}. Couples in your area are actively searching for premarital counseling, and we want them to find you.

If you want the complimentary founding listing, just reply "yes" and I will send the setup link.

Best,
Wedding Counselors Directory Team"""
    },
    {
        "step_number": 3,
        "delay_days": 5,  # 5 days after second email (8 days total)
        "subject_template": "Final note on your directory listing",
        "email_template": """Hi {firstName},

Final note from me about listing {company} in the Wedding Counselors Directory. If you want the complimentary founding listing, reply "yes" and I will send the link.

If it is not a fit, no worries and I will close the loop.

Wishing you all the best,
Wedding Counselors Directory Team"""
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
        print(f"  - Step 2: Follow-up (day 3)")
        print(f"  - Step 3: Final (day 8)")
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
