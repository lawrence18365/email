#!/usr/bin/env python3
"""
A/B Test Setup — Old Pitch vs New Conversation Approach.

IDEMPOTENT: Safe to run multiple times. Will not create duplicate campaigns
or double-assign leads. Detects existing state and only makes necessary changes.

Campaign A (ID=1): CONTROL — old pitch-first approach (4 steps over 15 days)
Campaign B (ID=2): Conversation approach, subject "quick question about your practice"
Campaign C (ID=3): Conversation approach, subject "do you work with engaged couples?"
Campaign D (ID=4): Conversation approach, subject "question about premarital counseling"

Campaigns B/C/D use 3-step conversation sequence:
  Step 1: Question (no pitch, no links, curiosity-driven)
  Step 2: Value + soft reveal (day 7)
  Step 3: Offer — "I made something for you" (day 14)

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


# ═══════════════════════════════════════════════════════════════════════════════
# CAMPAIGN A — CONTROL (old pitch-first approach, unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

CONTROL_BODIES = [
    # Step 1 (Day 0)
    (
        "Hi {firstName|there},\n\n"
        "{opener|I came across your practice and wanted to reach out.}\n\n"
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
    # Step 2 (Day 3)
    (
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
    # Step 3 (Day 8)
    (
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
    # Step 4 (Day 15)
    (
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
]

CONTROL_SUBJECTS = [
    "founding member spot for {industry} counselors",
    "re: founding member spot for {industry} counselors",
    "your founding member spot expires {deadline}",
    "last note — {firstName|your listing}",
]

CONTROL_DELAYS = [0, 3, 5, 7]


# ═══════════════════════════════════════════════════════════════════════════════
# CAMPAIGNS B/C/D — CONVERSATION-FIRST APPROACH (Cialdini-driven)
#
# Each email is built on specific Cialdini principles:
#
# Step 1 — LIKING + UNITY + COMMITMENT
#   Liking: Show genuine interest in their specific work
#   Unity: "We're both trying to help couples" (shared identity)
#   Commitment: Small ask (reply with perspective) → foot in door
#   Authority: Demonstrate insider knowledge of premarital space
#
# Step 2 — RECIPROCITY + SOCIAL PROOF + AUTHORITY
#   Reciprocity: Share valuable market data they can't get elsewhere
#   Social proof: "Other counselors I've spoken with say..."
#   Authority: "Already ranking in Google" — credibility without bragging
#   Commitment: Another small ask builds on the first
#
# Step 3 — RECIPROCITY (max) + SCARCITY (real) + SOCIAL PROOF
#   Reciprocity: "I already built this for you" — massive gift before ask
#   Scarcity: Endowment effect — "your profile" (theirs to lose, not gain)
#   Social proof: Other counselors nearby have already claimed theirs
# ═══════════════════════════════════════════════════════════════════════════════

# Step 1: The Question — LIKING + UNITY + COMMITMENT
# {opener} from enrichment contains a specific question about their practice.
# Fallback for un-enriched leads is a genuine generic question.
CONV_BODY_STEP1 = (
    "Hi {firstName|there},\n\n"
    "{opener|I came across your practice and had a quick question — "
    "do you work with couples before they get married, or mainly once "
    "they're already having issues?}\n\n"
    "I ask because I work in the premarital counseling space too, and "
    "I keep hearing from engaged couples that they want help but can't "
    "find a counselor nearby. Trying to understand if that gap matches "
    "what you're seeing from your side.\n\n"
    "Would love your take if you have a minute.\n\n"
    "Sarah"
)

# Step 2: The Value — RECIPROCITY + SOCIAL PROOF + AUTHORITY
CONV_BODY_STEP2 = (
    "Hi {firstName|there},\n\n"
    "Following up on my earlier question — wanted to share some context "
    "in case it's useful.\n\n"
    "I run WeddingCounselors.com, a directory specifically for counselors "
    "who work with couples before marriage. We're already ranking on the "
    "first page of Google for searches like \"premarital counseling near me\" "
    "in a lot of cities.\n\n"
    "Here's what I keep hearing from other counselors: most couples find "
    "them through referrals, not Google. But the online search demand is "
    "massive and growing — and most of those couples end up on generic "
    "directories that don't highlight the counselors who actually "
    "specialize in premarital work.\n\n"
    "Curious if that matches your experience, or if you've found a way "
    "to reach couples earlier in the process.\n\n"
    "Sarah"
)

# Step 3: The Offer — RECIPROCITY (max) + ENDOWMENT + SOCIAL PROOF
CONV_BODY_STEP3 = (
    "Hi {firstName|there},\n\n"
    "Last note from me — I went ahead and created a draft profile page "
    "for you on WeddingCounselors.com based on what I found on your "
    "website.\n\n"
    "Other counselors in your area have already claimed theirs, and "
    "they're starting to show up when couples search nearby.\n\n"
    "If you want to claim yours and make it live, takes about 2 minutes: "
    "https://www.weddingcounselors.com/professional/signup"
    "?utm_source=email&utm_medium=outreach&utm_campaign=conversation\n\n"
    "If not, no worries at all — I'll take the draft down.\n\n"
    "Either way, wishing your practice well.\n\n"
    "Sarah"
)

CONV_BODIES = [CONV_BODY_STEP1, CONV_BODY_STEP2, CONV_BODY_STEP3]
CONV_DELAYS = [0, 7, 14]  # weekly cadence — respectful for busy professionals


# ─── Variant Definitions ──────────────────────────────────────────────────────

VARIANTS = {
    "A": {
        "campaign_id": 1,
        "name": None,  # keep existing name
        "approach": "control",
        "subjects": CONTROL_SUBJECTS,
        "bodies": CONTROL_BODIES,
        "delays": CONTROL_DELAYS,
    },
    "B": {
        "campaign_id": 2,
        "name": None,
        "approach": "conversation",
        "subjects": [
            "quick question about your practice",
            "re: quick question about your practice",
            "made something for you",
        ],
        "bodies": CONV_BODIES,
        "delays": CONV_DELAYS,
    },
    "C": {
        "campaign_id": None,
        "name": "WC Outreach — Variant C (Google Visibility)",
        "approach": "conversation",
        "subjects": [
            "do you work with engaged couples?",
            "re: do you work with engaged couples?",
            "made something for you",
        ],
        "bodies": CONV_BODIES,
        "delays": CONV_DELAYS,
    },
    "D": {
        "campaign_id": None,
        "name": "WC Outreach — Variant D (Free Profile)",
        "approach": "conversation",
        "subjects": [
            "question about premarital counseling",
            "re: question about premarital counseling",
            "made something for you",
        ],
        "bodies": CONV_BODIES,
        "delays": CONV_DELAYS,
    },
}


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
    print(f"  Campaign A (control): {campaign_a.name} (ID=1)")
    print(f"  Campaign B (conversation): {campaign_b.name} (ID=2)")
    print(f"  Inbox: {campaign_a.inbox.email}")

    return campaign_a


def setup_campaigns(dry_run=False):
    """Create/update campaigns and their sequences. IDEMPOTENT."""
    print("=" * 60)
    print("A/B TEST: Pitch (control) vs Conversation (new)")
    print("=" * 60)

    with app.app_context():
        campaign_a = _validate_prerequisites()
        inbox_id = campaign_a.inbox_id

        campaign_ids = {}

        for variant_label, config in VARIANTS.items():
            print(f"\n{'─'*40}")
            print(f"Variant {variant_label} ({config['approach']})")

            if config["campaign_id"]:
                campaign = Campaign.query.get(config["campaign_id"])
                if not campaign:
                    print(f"  ERROR: Campaign ID={config['campaign_id']} not found, skipping")
                    continue
                print(f"  Campaign: {campaign.name} (ID={campaign.id}, existing)")
                campaign_ids[variant_label] = campaign.id
            else:
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

            subjects = config["subjects"]
            bodies = config["bodies"]
            delays = config["delays"]
            num_steps = len(subjects)

            # Create/update sequence steps
            for i, (subject, delay, body) in enumerate(zip(subjects, delays, bodies), 1):
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
                        print(f"  Step {i}: UPDATED | {old_subj!r} -> {subject!r}")
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

            # Deactivate extra steps (e.g. step 4 for conversation campaigns)
            extra_steps = Sequence.query.filter(
                Sequence.campaign_id == campaign.id,
                Sequence.step_number > num_steps,
                Sequence.active == True
            ).all()
            for extra in extra_steps:
                if dry_run:
                    print(f"  Step {extra.step_number}: [DRY RUN] would deactivate")
                else:
                    extra.active = False
                    print(f"  Step {extra.step_number}: DEACTIVATED (not needed for {config['approach']} approach)")

            if not dry_run:
                campaign.status = "active"
                db.session.commit()

        return campaign_ids


def redistribute_leads(campaign_ids, dry_run=False):
    """Redistribute untouched leads evenly across all campaigns. IDEMPOTENT."""
    print(f"\n{'='*60}")
    print("LEAD REDISTRIBUTION")
    print(f"{'='*60}")

    with app.app_context():
        real_ids = sorted([cid for cid in campaign_ids.values() if isinstance(cid, int)])
        if len(real_ids) < 2:
            if dry_run:
                print("  [DRY RUN] Would distribute across campaigns once created")
            else:
                print("  ERROR: Need at least 2 real campaign IDs to redistribute.")
            return

        # Check if leads are ALREADY distributed (idempotency)
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
            if min_count >= max_count * 0.7:
                print(f"\nLeads already distributed across all campaigns:")
                for cid, count in existing_distribution.items():
                    campaign = Campaign.query.get(cid)
                    print(f"  {campaign.name} (ID={cid}): {count} active leads")
                print(f"  Distribution is balanced (min={min_count}, max={max_count}). Skipping redistribution.")
                return

        # Find untouched leads
        sent_lead_ids = db.session.query(SentEmail.lead_id).distinct().subquery()
        untouched = Lead.query.filter(
            Lead.status == 'new',
            ~Lead.id.in_(sent_lead_ids)
        ).all()

        print(f"\nUntouched leads (status='new', never emailed): {len(untouched)}")

        if not untouched:
            print("No untouched leads to redistribute.")
            print("\nCurrent lead distribution:")
            for cid in real_ids:
                campaign = Campaign.query.get(cid)
                active = CampaignLead.query.filter_by(campaign_id=cid, status='active').count()
                print(f"  {campaign.name} (ID={cid}): {active} active leads")
            return

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

        # Remove existing assignments for untouched leads
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

        # Verify no duplicates
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
        print("\nA/B test setup complete.")
        print("Campaign A: Control (pitch-first, 4 steps)")
        print("Campaigns B/C/D: Conversation-first (3 steps)")
        print("Next cron run will send across all variants.")


if __name__ == "__main__":
    main()
