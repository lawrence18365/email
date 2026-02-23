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
    "max_per_hour": 13,  # Match current DB value (13/hr × 8hr window ≈ 104 capacity)
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
        "subject_template": "free listing for {industry} counselors",
        "email_template": """Hi {firstName|there},

I run WeddingCounselors.com — 5,000+ pages indexed by Google, all focused on premarital counseling. Couples in {industry} are already searching and finding counselors through us.

Here's what you'd get (free):

- Your own profile page, optimized to rank when couples search your area
- A contact form so couples can reach you directly — no middleman
- A dashboard showing your profile views and inquiries each week

Counselors like Dr. William Ryan and Martha Maurno are already getting couple inquiries through their profiles.

Founding member listings are free permanently. No credit card, no catch. After {deadline}, new counselors pay $29/month — but yours stays free forever once you're in.

Takes 2 minutes: https://www.weddingcounselors.com/professional/signup?utm_source=email&utm_medium=outreach&utm_campaign=founding_member

Or reply "yes" and I'll send you the details.

Sarah
Wedding Counselors Directory"""
    },
    {
        "step_number": 2,
        "delay_days": 3,
        "subject_template": "re: free listing for {industry} counselors",
        "email_template": """Quick follow-up — we had 35,000+ Google impressions last quarter alone, and couples are actively submitting inquiries through counselor profiles every week.

Your profile page would rank alongside 5,000+ indexed pages on our site. Founding members also get weekly visibility reports showing exactly how many couples viewed their profile and searched in their area.

We just crossed 1,500 counselors — most signed up in the last 60 days. The directory is growing fast and early members are getting the most visibility.

Still free, still no credit card. After {deadline}, new counselors pay $29/mo — that's for people who join later, not you once you're in.

2 minutes: https://www.weddingcounselors.com/professional/signup?utm_source=email&utm_medium=outreach&utm_campaign=founding_member

Or just reply "yes."

Sarah"""
    },
    {
        "step_number": 3,
        "delay_days": 5,
        "subject_template": "your free listing expires {deadline}",
        "email_template": """Hi {firstName|there},

Last note from me — after {deadline}, founding member listings close and new counselors pay $29/month.

Your listing is free permanently once you're in. You get your own page on a 5,000+ page directory that Google already indexes, a contact form for couple inquiries, and weekly visibility reports.

I can't extend the free offer to anyone who signs up after {deadline}.

Reply "yes" or sign up here: https://www.weddingcounselors.com/professional/signup?utm_source=email&utm_medium=outreach&utm_campaign=founding_member

Sarah"""
    },
    {
        "step_number": 4,
        "delay_days": 7,
        "subject_template": "closing your file",
        "email_template": """Hi {firstName|there},

I've reached out a few times about a free listing on WeddingCounselors.com — wanted to close the loop.

If it's not for you, no worries at all. I'll remove you from follow-ups.

If you do want in before founding member spots close on {deadline}, here's the link: https://www.weddingcounselors.com/professional/signup?utm_source=email&utm_medium=outreach&utm_campaign=founding_member

Either way, wishing you well.

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
