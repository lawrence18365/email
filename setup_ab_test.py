#!/usr/bin/env python3
"""
A/B Test Setup — Creates 4-variant subject line test.

IDEMPOTENT: Safe to run multiple times. Will not create duplicate campaigns
or double-assign leads. Detects existing state and only makes necessary changes.

Variant A (ID=1): "founding member spot for {industry} counselors" (control)
Variant B (ID=2): "couples searching for {industry} counselors near you"
Variant C (new):  "{industry} counselors: your Google visibility report"
Variant D (new):  "free profile page for {industry} counselors"

Email body is identical across all 4 variants to isolate subject line impact.

Run via: workflow_dispatch (Update WC Sequences workflow)
         python setup_ab_test.py --dry-run   # Preview only
         python setup_ab_test.py             # Apply changes
"""

import os
import sys
import random
import argparse
import logging

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app import app
from models import db, Campaign, Sequence, CampaignLead, Lead, SentEmail

# ─── Shared email body (proven template, only subjects differ) ───────────────

BODY_STEP1 = (
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
)

BODY_STEP2 = (
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
)

BODY_STEP3 = (
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
)

BODY_STEP4 = (
    "Hi {firstName|there},\n\n"
    "I've reached out a few times about a founding member spot on WeddingCounselors.com — "
    "wanted to close the loop.\n\n"
    "If it's not for you, no worries at all. I'll remove you from follow-ups.\n\n"
    "If you do want in before founding member spots close on {deadline}, here's the link: "
    "https://www.weddingcounselors.com/professional/signup"
    "?utm_source=email&utm_medium=outreach&utm_campaign=founding_member\n\n"
    "Either way, wishing you well.\n\n"
    "Sarah"
)

# ─── 4 Subject Line Variants ────────────────────────────────────────────────

VARIANTS = {
    "A": {
        "campaign_id": 1,  # existing
        "name": None,      # keep existing name
        "subjects": [
            "founding member spot for {industry} counselors",
            "re: founding member spot for {industry} counselors",
            "your founding member spot expires {deadline}",
            "last note — {company|your listing}",
        ],
    },
    "B": {
        "campaign_id": 2,  # existing
        "name": None,
        "subjects": [
            "couples searching for {industry} counselors near you",
            "re: couples searching for {industry} counselors near you",
            "couples in {industry} are looking for counselors like you",
            "last note — {company|your listing}",
        ],
    },
    "C": {
        "campaign_id": None,  # create new (unless already exists)
        "name": "WC Outreach — Variant C (Google Visibility)",
        "subjects": [
            "{industry} counselors: your Google visibility report",
            "re: {industry} counselors: your Google visibility report",
            "your {industry} counseling profile is missing from Google",
            "last note — {company|your listing}",
        ],
    },
    "D": {
        "campaign_id": None,  # create new (unless already exists)
        "name": "WC Outreach — Variant D (Free Profile)",
        "subjects": [
            "free profile page for {industry} counselors",
            "re: free profile page for {industry} counselors",
            "your free counselor profile expires {deadline}",
            "last note — {company|your listing}",
        ],
    },
}

STEP_DELAYS = [0, 3, 5, 7]  # days between steps
BODIES = [BODY_STEP1, BODY_STEP2, BODY_STEP3, BODY_STEP4]


def _validate_prerequisites():
    """Check that required campaigns and inbox exist before proceeding."""
    errors = []

    campaign_a = Campaign.query.get(1)
    if not campaign_a:
        errors.append("Campaign ID=1 not found")
    elif not campaign_a.inbox:
        errors.append("Campaign ID=1 has no inbox configured")
    elif not campaign_a.inbox.active:
        errors.append(f"Campaign ID=1 inbox ({campaign_a.inbox.email}) is not active")

    campaign_b = Campaign.query.get(2)
    if not campaign_b:
        errors.append("Campaign ID=2 not found — Variant B needs an existing campaign")

    if errors:
        print("PREREQUISITE CHECK FAILED:")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print("Prerequisites OK:")
    print(f"  Campaign A: {campaign_a.name} (ID=1)")
    print(f"  Campaign B: {campaign_b.name} (ID=2)")
    print(f"  Inbox: {campaign_a.inbox.email}")

    return campaign_a


def setup_campaigns(dry_run=False):
    """Create/update campaigns C & D and their sequences. IDEMPOTENT."""
    print("=" * 60)
    print("A/B TEST SETUP — 4 Subject Line Variants")
    print("=" * 60)

    with app.app_context():
        campaign_a = _validate_prerequisites()
        inbox_id = campaign_a.inbox_id

        campaign_ids = {}

        for variant_label, config in VARIANTS.items():
            print(f"\n{'─'*40}")
            print(f"Variant {variant_label}")

            if config["campaign_id"]:
                # Existing campaign — just update sequences
                campaign = Campaign.query.get(config["campaign_id"])
                if not campaign:
                    print(f"  ERROR: Campaign ID={config['campaign_id']} not found, skipping")
                    continue
                print(f"  Campaign: {campaign.name} (ID={campaign.id}, existing)")
                campaign_ids[variant_label] = campaign.id
            else:
                # Check if this campaign already exists (idempotency)
                existing = Campaign.query.filter_by(name=config["name"]).first()
                if existing:
                    campaign = existing
                    print(f"  Campaign already exists: {campaign.name} (ID={campaign.id})")
                    campaign_ids[variant_label] = campaign.id
                elif dry_run:
                    print(f"  [DRY RUN] Would create: {config['name']}")
                    campaign_ids[variant_label] = f"NEW-{variant_label}"
                else:
                    campaign = Campaign(
                        name=config["name"],
                        inbox_id=inbox_id,
                        status="active",
                    )
                    db.session.add(campaign)
                    db.session.flush()
                    campaign_ids[variant_label] = campaign.id
                    print(f"  CREATED: {campaign.name} (ID={campaign.id})")

            # Create/update 4 sequence steps
            for i, (subject, delay, body) in enumerate(zip(config["subjects"], STEP_DELAYS, BODIES), 1):
                if dry_run and not config["campaign_id"] and not Campaign.query.filter_by(name=config.get("name", "")).first():
                    print(f"  Step {i}: delay={delay}d | subject={subject!r}")
                    continue

                existing_seq = Sequence.query.filter_by(
                    campaign_id=campaign.id,
                    step_number=i
                ).first()

                if existing_seq:
                    changed = (
                        existing_seq.subject_template != subject or
                        existing_seq.email_template != body or
                        existing_seq.delay_days != delay
                    )
                    if changed:
                        old_subj = existing_seq.subject_template
                        existing_seq.subject_template = subject
                        existing_seq.email_template = body
                        existing_seq.delay_days = delay
                        existing_seq.active = True
                        print(f"  Step {i}: UPDATED | {old_subj!r} → {subject!r}")
                    else:
                        print(f"  Step {i}: OK (no changes needed)")
                else:
                    if dry_run:
                        print(f"  Step {i}: [DRY RUN] would create | {subject!r}")
                    else:
                        seq = Sequence(
                            campaign_id=campaign.id,
                            step_number=i,
                            delay_days=delay,
                            subject_template=subject,
                            email_template=body,
                            active=True,
                        )
                        db.session.add(seq)
                        print(f"  Step {i}: CREATED | {subject!r}")

            if not dry_run:
                campaign.status = "active"
                db.session.commit()

        return campaign_ids


def redistribute_leads(campaign_ids, dry_run=False):
    """Redistribute untouched leads evenly across all 4 campaigns. IDEMPOTENT."""
    print(f"\n{'='*60}")
    print("LEAD REDISTRIBUTION")
    print(f"{'='*60}")

    with app.app_context():
        # Get real campaign IDs (skip dry-run placeholders)
        real_ids = sorted([cid for cid in campaign_ids.values() if isinstance(cid, int)])
        if len(real_ids) < 2:
            if dry_run:
                print("  [DRY RUN] Would distribute across 4 campaigns once created")
            else:
                print("  ERROR: Need at least 2 real campaign IDs to redistribute.")
            return

        # Check if leads are ALREADY distributed across these campaigns
        # (idempotency: don't re-shuffle if already done)
        existing_distribution = {}
        for cid in real_ids:
            count = CampaignLead.query.filter_by(
                campaign_id=cid, status='active'
            ).count()
            existing_distribution[cid] = count

        all_have_leads = all(c > 0 for c in existing_distribution.values())
        total_assigned = sum(existing_distribution.values())

        if all_have_leads and total_assigned > 10:
            max_count = max(existing_distribution.values())
            min_count = min(existing_distribution.values())
            # If distribution is already reasonably balanced, skip redistribution
            if min_count >= max_count * 0.7:
                print(f"\nLeads already distributed across all campaigns:")
                for cid, count in existing_distribution.items():
                    campaign = Campaign.query.get(cid)
                    print(f"  {campaign.name} (ID={cid}): {count} active leads")
                print(f"  Distribution is balanced (min={min_count}, max={max_count}). Skipping redistribution.")
                return

        # Find all leads with status='new' and NO SentEmail records
        sent_lead_ids = db.session.query(SentEmail.lead_id).distinct().subquery()
        untouched = Lead.query.filter(
            Lead.status == 'new',
            ~Lead.id.in_(sent_lead_ids)
        ).all()

        print(f"\nUntouched leads (status='new', never emailed): {len(untouched)}")

        if not untouched:
            print("No untouched leads to redistribute.")
            # Show current state
            print("\nCurrent lead distribution:")
            for cid in real_ids:
                campaign = Campaign.query.get(cid)
                active = CampaignLead.query.filter_by(campaign_id=cid, status='active').count()
                print(f"  {campaign.name} (ID={cid}): {active} active leads")
            return

        # Shuffle randomly to prevent geographic/alphabetical bias
        random.shuffle(untouched)

        per_variant = len(untouched) // len(real_ids)
        remainder = len(untouched) % len(real_ids)
        print(f"Distributing across {len(real_ids)} campaigns: ~{per_variant} each")
        if remainder:
            print(f"  ({remainder} extra leads go to first {remainder} campaigns)")

        if dry_run:
            for i, cid in enumerate(real_ids):
                count = per_variant + (1 if i < remainder else 0)
                campaign = Campaign.query.get(cid)
                name = campaign.name if campaign else f"Campaign {cid}"
                print(f"  [DRY RUN] {name}: would get {count} leads")
            print(f"\n  Total: {len(untouched)} leads would be redistributed")
            return

        # Remove untouched leads from any existing CampaignLead assignments
        untouched_ids = [l.id for l in untouched]
        removed = CampaignLead.query.filter(
            CampaignLead.lead_id.in_(untouched_ids)
        ).delete(synchronize_session='fetch')
        if removed:
            print(f"Removed {removed} existing CampaignLead assignments for untouched leads")

        # Round-robin assign
        assigned = {cid: 0 for cid in real_ids}
        for i, lead in enumerate(untouched):
            target_campaign_id = real_ids[i % len(real_ids)]
            cl = CampaignLead(
                campaign_id=target_campaign_id,
                lead_id=lead.id,
                status='active',
            )
            db.session.add(cl)
            assigned[target_campaign_id] += 1

        db.session.commit()

        print("\nAssignment complete:")
        for cid, count in assigned.items():
            campaign = Campaign.query.get(cid)
            print(f"  {campaign.name} (ID={cid}): {count} leads")
        print(f"  Total: {sum(assigned.values())} leads redistributed")

        # Verify: check for leads in multiple A/B campaigns
        from sqlalchemy import func
        multi = db.session.query(
            CampaignLead.lead_id, func.count(CampaignLead.campaign_id)
        ).filter(
            CampaignLead.campaign_id.in_(real_ids),
            CampaignLead.status == 'active'
        ).group_by(CampaignLead.lead_id).having(
            func.count(CampaignLead.campaign_id) > 1
        ).count()
        if multi > 0:
            print(f"\n  WARNING: {multi} leads are in multiple A/B campaigns — investigate!")
        else:
            print(f"\n  Verified: no leads in multiple campaigns (clean test)")


def main():
    parser = argparse.ArgumentParser(description="A/B Test Setup")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    if args.dry_run:
        print("\n*** DRY RUN MODE — no changes will be made ***\n")

    campaign_ids = setup_campaigns(dry_run=args.dry_run)
    redistribute_leads(campaign_ids, dry_run=args.dry_run)

    if args.dry_run:
        print("\n*** DRY RUN COMPLETE — run without --dry-run to apply ***")
    else:
        print("\nA/B test setup complete. Next cron run will send across all 4 variants.")


if __name__ == "__main__":
    main()
