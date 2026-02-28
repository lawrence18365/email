#!/usr/bin/env python3
"""
Update shared email bodies and delay_days for all WC campaigns.

Subject lines are NOT updated here — setup_ab_test.py handles per-variant
subjects to preserve the A/B test. This script only updates:
  - email_template (body text, shared across all variants)
  - delay_days (step timing)
  - Creates missing sequence steps

Run via: GitHub Actions → "Update WC Sequences" workflow_dispatch
         (setup_ab_test.py runs after this to set per-variant subjects)
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

# Shared email bodies and timing — subjects are set by setup_ab_test.py
SEQUENCE_UPDATES = [
    {
        "step_number": 1,
        "delay_days": 0,
        "default_subject": "founding member spot for {industry} counselors",
        "email_template": (
            "Hi {firstName|there},\n\n"
            "I run WeddingCounselors.com — 5,000+ pages indexed by Google, all focused on "
            "premarital counseling. Couples in {industry} are already searching and finding "
            "counselors through us.\n\n"
            "Here's what you'd get as a founding member:\n\n"
            "- Your own profile page, optimized to rank when couples search your area\n"
            "- A contact form so couples can reach you directly — no middleman\n"
            "- A dashboard showing your profile views and inquiries each week\n\n"
            "Counselors like Dr. William Ryan and Martha Maurno are already getting "
            "couple inquiries through their profiles.\n\n"
            "Founding member listings are free permanently. No credit card, no catch. "
            "After {deadline}, new counselors pay $29/month — but yours stays free forever "
            "once you're in.\n\n"
            "Takes 2 minutes: https://www.weddingcounselors.com/professional/signup"
            "?utm_source=email&utm_medium=outreach&utm_campaign=founding_member\n\n"
            "Or reply \"yes\" and I'll send you the details.\n\n"
            "Sarah\n"
            "Wedding Counselors Directory"
        ),
    },
    {
        "step_number": 2,
        "delay_days": 3,
        "default_subject": "re: founding member spot for {industry} counselors",
        "email_template": (
            "Quick follow-up — we had 35,000+ Google impressions last quarter alone, and "
            "couples are actively submitting inquiries through counselor profiles every week.\n\n"
            "Your profile page would rank alongside 5,000+ indexed pages on our site. "
            "Founding members also get weekly visibility reports showing exactly how many "
            "couples viewed their profile and searched in their area.\n\n"
            "We just crossed 1,500 counselors — most signed up in the last 60 days. "
            "The directory is growing fast and early members are getting the most visibility.\n\n"
            "Still free, still no credit card. After {deadline}, new counselors pay $29/mo — "
            "that's for people who join later, not you once you're in.\n\n"
            "2 minutes: https://www.weddingcounselors.com/professional/signup"
            "?utm_source=email&utm_medium=outreach&utm_campaign=founding_member\n\n"
            "Or just reply \"yes.\"\n\n"
            "Sarah"
        ),
    },
    {
        "step_number": 3,
        "delay_days": 5,
        "default_subject": "your founding member spot expires {deadline}",
        "email_template": (
            "Hi {firstName|there},\n\n"
            "Last note from me — after {deadline}, founding member listings close and "
            "new counselors pay $29/month.\n\n"
            "Your listing is free permanently once you're in. You get your own page on a "
            "5,000+ page directory that Google already indexes, a contact form for couple "
            "inquiries, and weekly visibility reports.\n\n"
            "I can't extend the founding member offer to anyone who signs up after {deadline}.\n\n"
            "Reply \"yes\" or sign up here: https://www.weddingcounselors.com/professional/signup"
            "?utm_source=email&utm_medium=outreach&utm_campaign=founding_member\n\n"
            "Sarah"
        ),
    },
    {
        "step_number": 4,
        "delay_days": 7,
        "default_subject": "last note — {company|your listing}",
        "email_template": (
            "Hi {firstName|there},\n\n"
            "I've reached out a few times about a founding member spot on WeddingCounselors.com — "
            "wanted to close the loop.\n\n"
            "If it's not for you, no worries at all. I'll remove you from follow-ups.\n\n"
            "If you do want in before founding member spots close on {deadline}, here's the link: "
            "https://www.weddingcounselors.com/professional/signup"
            "?utm_source=email&utm_medium=outreach&utm_campaign=founding_member\n\n"
            "Either way, wishing you well.\n\n"
            "Sarah"
        ),
    },
]


def main():
    print("Updating WC sequence bodies and timing...")
    print("(Subject lines are handled by setup_ab_test.py to preserve A/B test)\n")

    with app.app_context():
        campaigns = Campaign.query.filter(
            Campaign.name.ilike('%wedding%')
        ).all()

        if not campaigns:
            print("ERROR: No Wedding Counselors campaigns found.")
            sys.exit(1)

        for campaign in campaigns:
            print(f"Campaign: {campaign.name} (ID: {campaign.id}, Status: {campaign.status})")

            for seq_data in SEQUENCE_UPDATES:
                seq = Sequence.query.filter_by(
                    campaign_id=campaign.id,
                    step_number=seq_data["step_number"]
                ).first()

                if seq:
                    changed = (
                        seq.email_template != seq_data["email_template"] or
                        seq.delay_days != seq_data["delay_days"]
                    )
                    if changed:
                        seq.email_template = seq_data["email_template"]
                        seq.delay_days = seq_data["delay_days"]
                        db.session.commit()
                        print(f"  Step {seq_data['step_number']}: UPDATED body/timing (subject unchanged: {seq.subject_template!r})")
                    else:
                        print(f"  Step {seq_data['step_number']}: OK (no changes needed)")
                else:
                    new_seq = Sequence(
                        campaign_id=campaign.id,
                        step_number=seq_data["step_number"],
                        delay_days=seq_data["delay_days"],
                        subject_template=seq_data["default_subject"],
                        email_template=seq_data["email_template"],
                        active=True,
                    )
                    db.session.add(new_seq)
                    db.session.commit()
                    print(f"  Step {seq_data['step_number']}: CREATED (subject: {seq_data['default_subject']!r})")

    print("\nDone. setup_ab_test.py will set per-variant subject lines next.")


if __name__ == "__main__":
    main()
