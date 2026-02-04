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
    "max_per_hour": 5,  # Conservative start - 10-15/day spread across hours
    "active": True
}

# Email templates with personalization variables
EMAIL_SEQUENCES = [
    {
        "step_number": 1,
        "delay_days": 0,  # Send immediately when added to campaign
        "subject_template": "Free listing for {company} on Wedding Counselors Directory",
        "email_template": """Hi {firstName},

I came across {company} and wanted to reach out personally.

We just launched Wedding Counselors Directory - a new platform specifically for clergy, pastors, and premarital counseling professionals to connect with engaged couples looking for guidance.

I'd love to offer you a free listing. It takes 2 minutes to set up and helps couples in your area find your services.

Would you be interested? Just reply "yes" and I'll send you the signup link.

Best,
Wedding Counselors Directory Team
https://weddingcounselors.com"""
    },
    {
        "step_number": 2,
        "delay_days": 3,  # 3 days after first email
        "subject_template": "Quick follow-up - free directory listing",
        "email_template": """Hi {firstName},

Just following up on my previous email about a free listing on Wedding Counselors Directory.

Many couples search online when looking for premarital counseling - we want to make sure they can find you.

Your free listing includes:
- Your profile and services
- Contact information
- Reviews from couples you've helped

Reply "interested" and I'll send the quick signup form.

Best,
Wedding Counselors Directory Team"""
    },
    {
        "step_number": 3,
        "delay_days": 5,  # 5 days after second email (8 days total)
        "subject_template": "Last chance - {company} directory listing",
        "email_template": """Hi {firstName},

Final note from me - I wanted to make sure you saw my earlier messages about listing {company} on our new Wedding Counselors Directory.

It's completely free and only takes a couple minutes. We're building the go-to resource for couples seeking premarital counseling, and I think you'd be a great fit.

If you're interested, just reply and I'll send the link. If not, no worries at all - I won't follow up again.

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
        existing_sequences = Sequence.query.filter_by(campaign_id=campaign.id).count()
        if existing_sequences > 0:
            print(f"Campaign already has {existing_sequences} sequences")
        else:
            for seq_config in EMAIL_SEQUENCES:
                sequence = Sequence(
                    campaign_id=campaign.id,
                    **seq_config
                )
                db.session.add(sequence)
            db.session.commit()
            print(f"Created {len(EMAIL_SEQUENCES)} email sequences")

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
