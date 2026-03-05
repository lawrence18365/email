#!/usr/bin/env python3
"""
A/B Test Analytics — Bulletproof funnel tracking with statistical significance.

Reply attribution: Uses SentEmail.campaign_id on the Response's linked sent_email,
NOT the CampaignLead junction table. This ensures replies are credited to the
campaign that actually sent the email, not whatever campaign the lead is assigned to.

OOO/bounce filtering: Out-of-office auto-replies and bounces are excluded from
reply counts since they don't represent real engagement.

Usage:
    python ab_analytics.py              # Full CLI report
    python ab_analytics.py --telegram   # Send daily A/B update to Telegram
    python ab_analytics.py --weekly     # Send weekly deep-dive to Telegram
    python ab_analytics.py --validate   # Run data integrity checks
"""

import os
import sys
import math
import argparse
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app import app
from models import db, Campaign, Sequence, CampaignLead, Lead, SentEmail, Response

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
TIMEZONE = os.environ.get('TIMEZONE', 'America/Los_Angeles')

# ─── Variant Label Mapping ──────────────────────────────────────────────────
# Hard-coded mapping based on actual campaign names/IDs. NOT sequential order,
# which would break if non-A/B campaigns exist (nudge, etc).

_VARIANT_CACHE = None


def _get_ab_campaigns() -> list:
    """Return only A/B test campaigns (not nudge/other campaigns), with labels."""
    global _VARIANT_CACHE
    if _VARIANT_CACHE is not None:
        return _VARIANT_CACHE

    all_active = Campaign.query.filter_by(status='active').order_by(Campaign.id).all()

    # Identify A/B test campaigns by name pattern or known IDs
    # Convention: A/B campaigns have "WC Outreach" or "Wedding Counselors" in name,
    # or are the first 2 campaigns (ID 1, 2) plus any Variant C/D campaigns.
    ab_campaigns = []
    label_iter = iter('ABCDEFGH')
    for c in all_active:
        name_lower = c.name.lower()
        # Include campaigns that are part of the A/B test
        is_ab = any(x in name_lower for x in [
            'outreach', 'wedding counselor', 'variant', 'wc ',
        ])
        # Also include campaign IDs 1 and 2 (original campaigns)
        if is_ab or c.id <= 2:
            label = next(label_iter, f"#{c.id}")
            ab_campaigns.append({
                'campaign': c,
                'label': label,
                'id': c.id,
                'name': c.name,
            })

    _VARIANT_CACHE = ab_campaigns
    return ab_campaigns


def _reset_cache():
    global _VARIANT_CACHE
    _VARIANT_CACHE = None


# ─── OOO / Bounce Detection ─────────────────────────────────────────────────

OOO_KEYWORDS = [
    'out of office', 'auto-reply', 'automatic reply', 'on vacation',
    'away from', 'out of the office', 'i am currently out',
    'i will be out', 'limited access to email', 'auto reply',
    'autoresponder', 'auto response',
]

BOUNCE_KEYWORDS = [
    'undeliverable', 'delivery failed', 'delivery status notification',
    'mail delivery failed', 'returned mail', 'delivery failure',
    'message not delivered', 'mailbox unavailable', 'user unknown',
    'no such user', 'address rejected',
]


def _is_ooo_or_bounce(response) -> bool:
    """Check if a response is an out-of-office or bounce (not real engagement)."""
    body = (response.body or '').lower()
    subject = (response.subject or '').lower()
    notes = (response.notes or '').lower()
    combined = subject + ' ' + body + ' ' + notes

    # Check notes field (cron_runner marks OOO with OOO_RETURN:)
    if 'ooo_return:' in notes:
        return True

    for kw in OOO_KEYWORDS + BOUNCE_KEYWORDS:
        if kw in combined:
            return True

    return False


# ─── Telegram ───────────────────────────────────────────────────────────────

def send_telegram_message(message: str) -> bool:
    """Send a message via Telegram bot."""
    import requests
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        logger.error(f"Telegram API error: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ─── Core Analytics Functions ────────────────────────────────────────────────

def get_variant_funnel(campaign_id: int, since: datetime = None) -> dict:
    """Full funnel for a single campaign/variant.

    Reply attribution: counts replies where the SENT EMAIL was from this campaign,
    not where the lead is currently assigned. This is the correct attribution for
    A/B testing — if Campaign A sent the email that got a reply, Campaign A gets
    the credit regardless of current CampaignLead state.
    """
    total_leads = CampaignLead.query.filter_by(campaign_id=campaign_id).count()

    # Distinct leads who received at least one email from this campaign
    emailed_q = db.session.query(
        db.func.count(db.func.distinct(SentEmail.lead_id))
    ).filter(
        SentEmail.campaign_id == campaign_id,
        SentEmail.status == 'sent'
    )
    if since:
        emailed_q = emailed_q.filter(SentEmail.sent_at >= since)
    emailed = emailed_q.scalar() or 0

    # Distinct leads who replied to emails FROM THIS CAMPAIGN
    # Join: Response.sent_email_id → SentEmail.id WHERE SentEmail.campaign_id = target
    replied_q = db.session.query(
        db.func.count(db.func.distinct(Response.lead_id))
    ).join(
        SentEmail, Response.sent_email_id == SentEmail.id
    ).filter(
        SentEmail.campaign_id == campaign_id
    )
    if since:
        replied_q = replied_q.filter(Response.received_at >= since)
    all_replies = replied_q.scalar() or 0

    # Filter out OOO/bounce replies for the "real" reply count
    # Need to check individual responses
    real_replied_leads = set()
    ooo_bounce_count = 0

    responses_for_campaign = db.session.query(Response).join(
        SentEmail, Response.sent_email_id == SentEmail.id
    ).filter(
        SentEmail.campaign_id == campaign_id
    )
    if since:
        responses_for_campaign = responses_for_campaign.filter(Response.received_at >= since)

    for resp in responses_for_campaign.all():
        if _is_ooo_or_bounce(resp):
            ooo_bounce_count += 1
        else:
            real_replied_leads.add(resp.lead_id)

    replied = len(real_replied_leads)

    # Leads who signed up (from this campaign's CampaignLead pool)
    campaign_lead_ids = db.session.query(CampaignLead.lead_id).filter_by(
        campaign_id=campaign_id
    ).subquery()
    signed_up = db.session.query(db.func.count(Lead.id)).filter(
        Lead.id.in_(campaign_lead_ids),
        Lead.status == 'signed_up'
    ).scalar() or 0

    reply_rate = (replied / emailed * 100) if emailed > 0 else 0
    conversion_rate = (signed_up / emailed * 100) if emailed > 0 else 0

    return {
        'total_leads': total_leads,
        'emailed': emailed,
        'replied': replied,
        'replied_total': all_replies,  # includes OOO/bounce
        'ooo_bounce': ooo_bounce_count,
        'signed_up': signed_up,
        'reply_rate': reply_rate,
        'conversion_rate': conversion_rate,
    }


def get_step_performance(campaign_id: int) -> list:
    """Per-step sent/reply breakdown. Uses efficient batch queries."""
    sequences = Sequence.query.filter_by(
        campaign_id=campaign_id, active=True
    ).order_by(Sequence.step_number).all()

    if not sequences:
        return []

    results = []

    for seq in sequences:
        # Count sent for this step
        sent = SentEmail.query.filter_by(
            campaign_id=campaign_id,
            sequence_id=seq.id,
            status='sent'
        ).count()

        # Count real replies attributed to this step's emails
        # A reply belongs to a step if:
        #   1. Response.sent_email_id → SentEmail.sequence_id = this sequence
        # This is the correct attribution: the reply links to the exact email
        replied = 0
        if sent > 0:
            step_responses = db.session.query(Response).join(
                SentEmail, Response.sent_email_id == SentEmail.id
            ).filter(
                SentEmail.campaign_id == campaign_id,
                SentEmail.sequence_id == seq.id,
            ).all()

            for resp in step_responses:
                if not _is_ooo_or_bounce(resp):
                    replied += 1

        reply_rate = (replied / sent * 100) if sent > 0 else 0
        results.append({
            'step': seq.step_number,
            'subject': seq.subject_template,
            'sent': sent,
            'replied': replied,
            'reply_rate': reply_rate,
        })

    return results


def get_daily_sends(campaign_id: int) -> dict:
    """Today's and yesterday's send/reply counts for a campaign."""
    tz = ZoneInfo(TIMEZONE)
    local_now = datetime.now(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = local_midnight.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    yesterday_start_utc = today_start_utc - timedelta(days=1)

    sent_today = SentEmail.query.filter(
        SentEmail.campaign_id == campaign_id,
        SentEmail.status == 'sent',
        SentEmail.sent_at >= today_start_utc
    ).count()

    sent_yesterday = SentEmail.query.filter(
        SentEmail.campaign_id == campaign_id,
        SentEmail.status == 'sent',
        SentEmail.sent_at >= yesterday_start_utc,
        SentEmail.sent_at < today_start_utc
    ).count()

    # Today's real replies (attributed to this campaign's emails)
    today_responses = db.session.query(Response).join(
        SentEmail, Response.sent_email_id == SentEmail.id
    ).filter(
        SentEmail.campaign_id == campaign_id,
        Response.received_at >= today_start_utc
    ).all()

    replies_today = sum(1 for r in today_responses if not _is_ooo_or_bounce(r))

    return {
        'sent_today': sent_today,
        'sent_yesterday': sent_yesterday,
        'replies_today': replies_today,
    }


def get_weekly_trend(campaign_id: int, weeks: int = 4) -> list:
    """Sent and replied counts per calendar week (Monday-aligned)."""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Align to Monday of the current week
    days_since_monday = now.weekday()
    this_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)

    results = []

    for w in range(weeks - 1, -1, -1):
        week_start = this_monday - timedelta(weeks=w)
        week_end = week_start + timedelta(days=7)

        # Convert to UTC for DB queries
        ws_utc = week_start.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
        we_utc = week_end.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)

        sent = SentEmail.query.filter(
            SentEmail.campaign_id == campaign_id,
            SentEmail.status == 'sent',
            SentEmail.sent_at >= ws_utc,
            SentEmail.sent_at < we_utc
        ).count()

        week_responses = db.session.query(Response).join(
            SentEmail, Response.sent_email_id == SentEmail.id
        ).filter(
            SentEmail.campaign_id == campaign_id,
            Response.received_at >= ws_utc,
            Response.received_at < we_utc
        ).all()

        replied = sum(1 for r in week_responses if not _is_ooo_or_bounce(r))

        iso_week = week_start.isocalendar()[1]
        reply_rate = (replied / sent * 100) if sent > 0 else 0

        results.append({
            'week': f"W{iso_week}",
            'sent': sent,
            'replied': replied,
            'reply_rate': reply_rate,
        })

    return results


def statistical_significance(rate_a: float, n_a: int, rate_b: float, n_b: int) -> dict:
    """Z-test for two proportions. No external dependencies."""
    if n_a == 0 or n_b == 0:
        return {'p_value': 1.0, 'significant': False, 'confidence': 0, 'min_sample': 'N/A'}

    p_a = rate_a / 100
    p_b = rate_b / 100

    # Pooled proportion
    p_pool = (p_a * n_a + p_b * n_b) / (n_a + n_b)

    if p_pool == 0 or p_pool == 1:
        return {'p_value': 1.0, 'significant': False, 'confidence': 0, 'min_sample': 'N/A'}

    # Standard error
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n_a + 1/n_b))
    if se == 0:
        return {'p_value': 1.0, 'significant': False, 'confidence': 0, 'min_sample': 'N/A'}

    z = abs(p_a - p_b) / se

    p_value = _z_to_p(z)
    confidence = (1 - p_value) * 100

    diff = abs(p_a - p_b)
    if diff > 0:
        z_alpha = 1.96
        z_beta = 0.84
        min_sample = int(
            (z_alpha + z_beta) ** 2 * (p_a * (1 - p_a) + p_b * (1 - p_b)) / diff ** 2
        )
    else:
        min_sample = 'N/A (identical rates)'

    return {
        'p_value': round(p_value, 4),
        'significant': p_value < 0.05,
        'confidence': round(confidence, 1),
        'min_sample': min_sample,
    }


def _z_to_p(z: float) -> float:
    """Convert Z-score to two-tailed p-value using rational approximation."""
    if z < 0:
        z = -z
    t = 1 / (1 + 0.2316419 * z)
    d = 0.3989423 * math.exp(-z * z / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
    return 2 * p


# ─── Data Integrity Checks ──────────────────────────────────────────────────

def validate_data_integrity() -> list:
    """Run integrity checks and return list of issues found."""
    issues = []

    with app.app_context():
        _reset_cache()
        ab_campaigns = _get_ab_campaigns()

        if not ab_campaigns:
            issues.append("CRITICAL: No A/B test campaigns found")
            return issues

        # Check 1: All campaigns have sequences
        for vc in ab_campaigns:
            c = vc['campaign']
            seq_count = Sequence.query.filter_by(campaign_id=c.id, active=True).count()
            if seq_count == 0:
                issues.append(f"CRITICAL: Variant {vc['label']} ({c.name}) has 0 active sequences")
            elif seq_count != 4:
                issues.append(f"WARNING: Variant {vc['label']} has {seq_count} sequences (expected 4)")

        # Check 2: All campaigns use same inbox
        inbox_ids = set()
        for vc in ab_campaigns:
            inbox_ids.add(vc['campaign'].inbox_id)
        if len(inbox_ids) > 1:
            issues.append(f"WARNING: A/B campaigns use {len(inbox_ids)} different inboxes — deliverability won't be controlled")

        # Check 3: Lead distribution balance
        lead_counts = {}
        for vc in ab_campaigns:
            active = CampaignLead.query.filter_by(
                campaign_id=vc['id'], status='active'
            ).count()
            lead_counts[vc['label']] = active

        if lead_counts:
            max_leads = max(lead_counts.values())
            min_leads = min(lead_counts.values())
            if max_leads > 0 and min_leads < max_leads * 0.7:
                issues.append(
                    f"WARNING: Lead imbalance — {lead_counts}. "
                    f"Max ({max_leads}) is {((max_leads - min_leads) / max_leads * 100):.0f}% more than min ({min_leads})"
                )

        # Check 4: Send balance (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        send_counts = {}
        for vc in ab_campaigns:
            sent = SentEmail.query.filter(
                SentEmail.campaign_id == vc['id'],
                SentEmail.status == 'sent',
                SentEmail.sent_at >= week_ago
            ).count()
            send_counts[vc['label']] = sent

        if any(v > 0 for v in send_counts.values()):
            max_sent = max(send_counts.values())
            min_sent = min(send_counts.values())
            if max_sent > 10 and min_sent < max_sent * 0.6:
                issues.append(
                    f"WARNING: Send imbalance last 7d — {send_counts}. "
                    f"Round-robin may not be working correctly"
                )

        # Check 5: Orphan responses (no sent_email_id link)
        orphan_count = Response.query.filter(
            Response.sent_email_id.is_(None)
        ).count()
        if orphan_count > 0:
            issues.append(
                f"INFO: {orphan_count} responses have no sent_email_id (matched by email, not header). "
                f"These won't be attributed to any A/B variant"
            )

        # Check 6: Leads in multiple A/B campaigns
        ab_campaign_ids = [vc['id'] for vc in ab_campaigns]
        if len(ab_campaign_ids) >= 2:
            from sqlalchemy import func
            multi = db.session.query(
                CampaignLead.lead_id, func.count(CampaignLead.campaign_id)
            ).filter(
                CampaignLead.campaign_id.in_(ab_campaign_ids),
                CampaignLead.status == 'active'
            ).group_by(CampaignLead.lead_id).having(
                func.count(CampaignLead.campaign_id) > 1
            ).count()
            if multi > 0:
                issues.append(
                    f"CRITICAL: {multi} leads are active in multiple A/B campaigns. "
                    f"This contaminates the test — each lead should be in exactly 1 variant"
                )

    return issues


# ─── Report Generators ──────────────────────────────────────────────────────

def generate_cli_report():
    """Print full A/B test report to stdout."""
    with app.app_context():
        _reset_cache()
        ab_campaigns = _get_ab_campaigns()

        if not ab_campaigns:
            print("No A/B test campaigns found.")
            return

        print("=" * 72)
        print("A/B TEST REPORT")
        print(f"Generated: {datetime.now(ZoneInfo(TIMEZONE)).strftime('%Y-%m-%d %H:%M %Z')}")
        print("=" * 72)

        # ── Data integrity ──
        issues = validate_data_integrity()
        if issues:
            print(f"\n{'!'*72}")
            print("DATA INTEGRITY CHECKS")
            print(f"{'!'*72}")
            for issue in issues:
                print(f"  {issue}")

        # ── Funnel comparison ──
        funnels = {}
        for vc in ab_campaigns:
            funnels[vc['label']] = get_variant_funnel(vc['id'])
            funnels[vc['label']]['name'] = vc['name']

        print(f"\n{'Variant':<10} {'Leads':>6} {'Sent':>6} {'Replied':>8} {'OOO/Bnc':>8} {'SignUp':>7} {'Reply%':>8} {'Conv%':>7}")
        print("-" * 72)
        for label, f in funnels.items():
            print(f"{label:<10} {f['total_leads']:>6} {f['emailed']:>6} {f['replied']:>8} "
                  f"{f['ooo_bounce']:>8} {f['signed_up']:>7} {f['reply_rate']:>7.1f}% {f['conversion_rate']:>6.1f}%")

        # ── Leader ──
        qualified = {k: v for k, v in funnels.items() if v['emailed'] >= 10}
        if qualified:
            best = max(qualified.items(), key=lambda x: x[1]['reply_rate'])
            print(f"\nLeader: Variant {best[0]} — {best[1]['name']}")
            print(f"  {best[1]['reply_rate']:.1f}% reply rate ({best[1]['replied']} replies / {best[1]['emailed']} sent)")

        # ── Today's activity ──
        print(f"\n{'─'*72}")
        print("TODAY'S SENDS (round-robin fairness check)")
        print(f"{'─'*72}")
        total_today = 0
        for vc in ab_campaigns:
            daily = get_daily_sends(vc['id'])
            total_today += daily['sent_today']
            print(f"  Variant {vc['label']}: {daily['sent_today']} sent, {daily['replies_today']} replies "
                  f"(yesterday: {daily['sent_yesterday']} sent)")
        print(f"  Total today: {total_today}")

        # ── Statistical significance ──
        print(f"\n{'─'*72}")
        print("STATISTICAL SIGNIFICANCE (each vs Variant A)")
        print(f"{'─'*72}")
        labels = list(funnels.keys())
        if len(labels) >= 2:
            control = funnels[labels[0]]
            for label in labels[1:]:
                f = funnels[label]
                sig = statistical_significance(
                    control['reply_rate'], control['emailed'],
                    f['reply_rate'], f['emailed']
                )
                status = "SIGNIFICANT" if sig['significant'] else "not yet"
                print(f"  A vs {label}: p={sig['p_value']:.4f} ({sig['confidence']:.1f}% confidence) "
                      f"— {status}")
                if isinstance(sig['min_sample'], int):
                    print(f"         need ~{sig['min_sample']}/variant for significance")

        # ── Step performance per variant ──
        for vc in ab_campaigns:
            steps = get_step_performance(vc['id'])
            print(f"\n{'─'*72}")
            print(f"STEP PERFORMANCE — Variant {vc['label']} ({vc['name']})")
            print(f"{'─'*72}")
            print(f"  {'Step':<6} {'Sent':>6} {'Replied':>8} {'Rate':>7}  Subject")
            for s in steps:
                subj = s['subject'][:42] + '...' if len(s['subject']) > 42 else s['subject']
                print(f"  {s['step']:<6} {s['sent']:>6} {s['replied']:>8} {s['reply_rate']:>6.1f}%  {subj}")

        # ── Weekly trend ──
        print(f"\n{'─'*72}")
        print("WEEKLY TREND (Monday-aligned)")
        print(f"{'─'*72}")
        for vc in ab_campaigns:
            trend = get_weekly_trend(vc['id'])
            print(f"  Variant {vc['label']}: ", end="")
            parts = []
            for w in trend:
                parts.append(f"{w['week']}={w['sent']}s/{w['replied']}r({w['reply_rate']:.0f}%)")
            print(" | ".join(parts))

        print()


def send_telegram_daily():
    """Send daily A/B comparison to Telegram. Self-gates on hour=17 PT."""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    if now.hour != 17:
        logger.info(f"Not 5 PM PT (current: {now.hour}:{now.minute}), skipping daily A/B update")
        return

    with app.app_context():
        _reset_cache()
        ab_campaigns = _get_ab_campaigns()
        if not ab_campaigns:
            logger.warning("No A/B campaigns found, skipping daily update")
            return

        def _esc(s):
            return (s or '').replace('<', '&lt;').replace('>', '&gt;')

        funnels = {}
        daily_data = {}
        for vc in ab_campaigns:
            funnels[vc['label']] = get_variant_funnel(vc['id'])
            daily_data[vc['label']] = get_daily_sends(vc['id'])

        qualified = {k: v for k, v in funnels.items() if v['emailed'] >= 10}
        leader = max(qualified.items(), key=lambda x: x[1]['reply_rate']) if qualified else None

        msg = f"📊 <b>A/B TEST — DAILY UPDATE</b>\n{now.strftime('%b %d, %Y')}\n{'─'*28}\n\n"

        # Today's activity first (most actionable)
        total_sent_today = sum(d['sent_today'] for d in daily_data.values())
        total_replies_today = sum(d['replies_today'] for d in daily_data.values())
        msg += f"<b>TODAY</b>: {total_sent_today} sent | {total_replies_today} replies\n"
        for label, d in daily_data.items():
            msg += f"  {_esc(label)}: {d['sent_today']} sent, {d['replies_today']} replies\n"

        # Cumulative funnel
        msg += f"\n<b>CUMULATIVE</b>\n"
        for label, f in funnels.items():
            is_leader = leader and label == leader[0]
            crown = " 👑" if is_leader else ""
            ooo_note = f" ({f['ooo_bounce']} OOO/bnc filtered)" if f['ooo_bounce'] > 0 else ""
            msg += (
                f"  <b>{_esc(label)}</b>{crown}: "
                f"{f['emailed']} sent → {f['replied']} replied ({f['reply_rate']:.1f}%)"
                f"{ooo_note}\n"
            )

        if leader:
            msg += f"\n👑 <b>{_esc(leader[0])}</b> leads at {leader[1]['reply_rate']:.1f}%"

            control_label = list(funnels.keys())[0]
            if leader[0] != control_label:
                control = funnels[control_label]
                sig = statistical_significance(
                    control['reply_rate'], control['emailed'],
                    leader[1]['reply_rate'], leader[1]['emailed']
                )
                if sig['significant']:
                    msg += f"\n✅ Significant (p={sig['p_value']:.3f})"
                else:
                    remaining = ""
                    if isinstance(sig['min_sample'], int) and sig['min_sample'] > max(control['emailed'], leader[1]['emailed']):
                        needed = sig['min_sample'] - max(control['emailed'], leader[1]['emailed'])
                        days_est = int(needed / 12) if needed > 0 else 0  # ~12/variant/day
                        remaining = f", ~{days_est}d more"
                    msg += f"\n⏳ Not yet (p={sig['p_value']:.3f}, need ~{sig['min_sample']}/var{remaining})"

        # Data quality flag
        issues = validate_data_integrity()
        critical = [i for i in issues if i.startswith('CRITICAL')]
        if critical:
            msg += f"\n\n⚠️ {len(critical)} data issue(s) — run --validate"

        send_telegram_message(msg)
        logger.info("Daily A/B update sent to Telegram")


def send_telegram_weekly():
    """Send comprehensive weekly A/B deep-dive to Telegram."""
    with app.app_context():
        _reset_cache()
        ab_campaigns = _get_ab_campaigns()
        if not ab_campaigns:
            return

        now = datetime.now(ZoneInfo(TIMEZONE))

        def _esc(s):
            return (s or '').replace('<', '&lt;').replace('>', '&gt;')

        msg = f"📋 <b>A/B TEST — WEEKLY REPORT</b>\n{now.strftime('%b %d, %Y')}\n{'─'*32}\n\n"

        # ── Funnel comparison ──
        funnels = {}
        for vc in ab_campaigns:
            funnels[vc['label']] = get_variant_funnel(vc['id'])
            funnels[vc['label']]['name'] = vc['name']

        msg += "<b>FULL FUNNEL</b>\n"
        msg += f"{'':>2}{'Var':<4} {'Sent':>5} {'Reply':>5} {'Rate':>6} {'OOO':>4} {'Sign':>4}\n"
        for label, f in funnels.items():
            msg += (
                f"  <b>{_esc(label)}</b>   {f['emailed']:>5} {f['replied']:>5} "
                f"{f['reply_rate']:>5.1f}% {f['ooo_bounce']:>4} {f['signed_up']:>4}\n"
            )

        # ── Leader ──
        qualified = {k: v for k, v in funnels.items() if v['emailed'] >= 10}
        if qualified:
            leader = max(qualified.items(), key=lambda x: x[1]['reply_rate'])
            msg += f"\n👑 Leader: <b>{_esc(leader[0])}</b> ({leader[1]['reply_rate']:.1f}%)\n"

        # ── Statistical significance ──
        msg += f"\n<b>STAT SIG (vs A)</b>\n"
        labels = list(funnels.keys())
        if len(labels) >= 2:
            control = funnels[labels[0]]
            for label in labels[1:]:
                f = funnels[label]
                sig = statistical_significance(
                    control['reply_rate'], control['emailed'],
                    f['reply_rate'], f['emailed']
                )
                icon = "✅" if sig['significant'] else "⏳"
                msg += f"  {icon} A vs {_esc(label)}: p={sig['p_value']:.3f}"
                if not sig['significant'] and isinstance(sig['min_sample'], int):
                    msg += f" (need ~{sig['min_sample']})"
                msg += "\n"

        # ── Step 1 performance (the subject line being tested) ──
        msg += f"\n<b>STEP 1 (SUBJECT LINE TEST)</b>\n"
        for vc in ab_campaigns:
            steps = get_step_performance(vc['id'])
            if steps:
                s1 = steps[0]
                subj = s1['subject'][:35]
                msg += f"  {_esc(vc['label'])}: {s1['sent']}s→{s1['replied']}r ({s1['reply_rate']:.1f}%)\n"
                msg += f"      \"{_esc(subj)}\"\n"

        # ── Send balance (fairness check) ──
        msg += f"\n<b>SEND BALANCE (7d)</b>\n"
        for vc in ab_campaigns:
            trend = get_weekly_trend(vc['id'], weeks=1)
            if trend:
                w = trend[0]
                msg += f"  {_esc(vc['label'])}: {w['sent']} sent, {w['replied']} replied\n"

        # ── Weekly trend ──
        msg += f"\n<b>TREND (4 weeks)</b>\n"
        for vc in ab_campaigns:
            trend = get_weekly_trend(vc['id'])
            parts = []
            for w in trend:
                if w['sent'] > 0:
                    parts.append(f"{w['week']}:{w['replied']}/{w['sent']}")
            if parts:
                msg += f"  {_esc(vc['label'])}: {' | '.join(parts)}\n"

        # ── Data integrity ──
        issues = validate_data_integrity()
        if issues:
            msg += f"\n<b>DATA QUALITY ({len(issues)} issues)</b>\n"
            for issue in issues[:5]:
                msg += f"  • {_esc(issue[:80])}\n"

        send_telegram_message(msg)
        logger.info("Weekly A/B report sent to Telegram")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='A/B Test Analytics')
    parser.add_argument('--telegram', action='store_true', help='Send daily A/B update to Telegram')
    parser.add_argument('--weekly', action='store_true', help='Send weekly A/B deep-dive to Telegram')
    parser.add_argument('--validate', action='store_true', help='Run data integrity checks')
    args = parser.parse_args()

    if args.validate:
        with app.app_context():
            _reset_cache()
            issues = validate_data_integrity()
            if issues:
                print(f"Found {len(issues)} issue(s):")
                for issue in issues:
                    print(f"  {issue}")
            else:
                print("All data integrity checks passed.")
    elif args.telegram:
        send_telegram_daily()
    elif args.weekly:
        send_telegram_weekly()
    else:
        generate_cli_report()


if __name__ == "__main__":
    main()
