#!/usr/bin/env python3
"""
One-time script to update Wedding Counselors email sequences with
psychology-optimized copy. Run via GitHub Actions workflow_dispatch.

Uses the same Flask/SQLAlchemy app context as the cron — proven to work.

Changes applied:
  - "Free permanently" framing lands before any $29/month mention
  - Explicit "no credit card, no catch" in every email
  - Deadline reframed: affects new signups, not the person receiving this email
  - Endowment effect: "your spot", "yours stays free forever once you're in"
  - "Reply yes" low-friction CTA added to emails 1 & 2
  - All emails tightened under 80 words
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app
from models import db, Campaign, Sequence

# Hard deadline — matches AI_REPLY_CONTEXT.md exactly so emails and AI replies are consistent.
DEADLINE = "March 15"

NEW_SEQUENCES = [
    {
        "step_number": 1,
        "delay_days": 0,
        "subject_template": "couple inquiry in {industry} — want in?",
        "email_template": (
            "Hi {firstName|there},\n\n"
            "I'm building WeddingCounselors.com — a directory dedicated to premarital counseling. "
            "We crossed 1,500 counselors this month and we're generating leads from couples in {industry} right now.\n\n"
            f"Founding member listings are free — permanently. No credit card, no catch. "
            f"After {DEADLINE}, new counselors pay $29/month. Yours stays free forever once you're in.\n\n"
            "Takes 2 minutes: https://www.weddingcounselors.com/professional/signup\n\n"
            "Or reply \"yes\" and I'll walk you through it.\n\n"
            "Sarah\n"
            "Wedding Counselors Directory"
        ),
    },
    {
        "step_number": 2,
        "delay_days": 3,
        "subject_template": "re: couple inquiry in {industry}",
        "email_template": (
            "Quick follow-up — founding members are already getting weekly visibility reports "
            "showing real profile views and couple inquiries from people searching in their area.\n\n"
            f"Your spot is still open. Free forever, no credit card. "
            f"After {DEADLINE}, new counselors pay $29/mo — that's for people who join after that date, "
            "not you once you're in.\n\n"
            "2 minutes: https://www.weddingcounselors.com/professional/signup\n\n"
            "Or reply \"yes.\"\n\n"
            "Sarah"
        ),
    },
    {
        "step_number": 3,
        "delay_days": 5,
        "subject_template": f"your free listing expires {DEADLINE}",
        "email_template": (
            "Hi {firstName|there},\n\n"
            f"Last note from me — after {DEADLINE}, founding member listings close and new counselors pay $29/month.\n\n"
            "Your listing is free permanently once you're in. "
            f"I can't extend that to anyone who signs up after {DEADLINE}.\n\n"
            "Reply \"yes\" or sign up here: https://www.weddingcounselors.com/professional/signup\n\n"
            "Sarah"
        ),
    },
]


def main():
    print("Updating Wedding Counselors email sequences...\n")

    with app.app_context():
        campaigns = Campaign.query.filter(
            Campaign.name.ilike('%wedding%')
        ).all()

        if not campaigns:
            print("ERROR: No Wedding Counselors campaigns found.")
            sys.exit(1)

        for campaign in campaigns:
            print(f"Campaign: {campaign.name} (ID: {campaign.id}, Status: {campaign.status})")

            for seq_data in NEW_SEQUENCES:
                seq = Sequence.query.filter_by(
                    campaign_id=campaign.id,
                    step_number=seq_data["step_number"]
                ).first()

                if seq:
                    old_subject    = seq.subject_template
                    old_delay_days = seq.delay_days
                    seq.subject_template = seq_data["subject_template"]
                    seq.email_template   = seq_data["email_template"]
                    seq.delay_days       = seq_data["delay_days"]
                    db.session.commit()
                    print(f"  Step {seq_data['step_number']}: updated")
                    print(f"    subject: {old_subject!r} → {seq_data['subject_template']!r}")
                    print(f"    delay:   {old_delay_days}d → {seq_data['delay_days']}d")
                else:
                    print(f"  Step {seq_data['step_number']}: not found, skipping")

    print("\nAll done.")


if __name__ == "__main__":
    main()
