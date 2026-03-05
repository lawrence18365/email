#!/usr/bin/env python3
"""
Telegram Notifier — Real-time campaign updates

Sends Telegram notifications for:
- New email replies (from DB responses, tracked via `notified` column)
- AI auto-reply confirmations
- Lead status alerts
- Daily campaign summary

Uses database `notified` column to track which responses have been
notified, so state persists across GitHub Actions runs.
"""

import os
import re
import sys
import logging
from datetime import datetime, timedelta

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

from app import app, _ensure_response_columns
from models import db, Inbox, Response, Lead, CampaignLead, Campaign, SentEmail

# Run lightweight migrations before any queries
with app.app_context():
    _ensure_response_columns()


def send_telegram_message(message: str) -> bool:
    """Send a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram notification sent")
            return True
        else:
            logger.error(f"Telegram API error: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def check_new_responses():
    """Safety-net notification for responses the AI responder didn't handle.

    The AI responder is the primary notification source — it sets
    notified=True after sending its own Telegram alert. This function
    only picks up responses that somehow slipped through (e.g. AI
    responder didn't run, or a new response arrived between steps).

    Uses the `notified` boolean column on the Response model so that
    notification state persists in the database.
    """
    with app.app_context():
        # Only notify about responses the AI responder hasn't already handled
        pending = Response.query.filter_by(notified=False).order_by(
            Response.received_at.desc()
        ).limit(50).all()

        new_count = 0

        for resp in pending:
            lead = resp.lead
            if not lead:
                resp.notified = True
                db.session.commit()
                continue

            # If AI already reviewed this, it should have set notified=True.
            # If we're here with reviewed=True but notified=False, just fix the flag.
            if resp.reviewed:
                resp.notified = True
                db.session.commit()
                continue

            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            company = lead.company or ""
            body_preview = (resp.body or "")[:300]
            body_preview = body_preview.replace('<', '&lt;').replace('>', '&gt;')
            name = name.replace('<', '&lt;').replace('>', '&gt;')

            notification = (
                f"<b>New Reply (unprocessed)</b>\n\n"
                f"<b>From:</b> {name}"
                + (f" ({company})" if company else "") + "\n"
                f"<b>Email:</b> {lead.email}\n"
                f"<b>Subject:</b> {resp.subject or '(no subject)'}\n\n"
                f"<b>Message:</b>\n{body_preview}"
                + ("..." if len(resp.body or "") > 300 else "")
            )

            if send_telegram_message(notification):
                resp.notified = True
                db.session.commit()
                new_count += 1
                logger.info(f"Notified (safety-net): reply from {lead.email}")

        if new_count > 0:
            logger.info(f"Sent {new_count} safety-net notifications")
        else:
            logger.info("No unprocessed responses to notify about")


def check_lead_status():
    """Check lead counts and alert if running low."""
    with app.app_context():
        campaigns = Campaign.query.filter_by(status='active').all()

        for campaign in campaigns:
            active = CampaignLead.query.filter_by(
                campaign_id=campaign.id, status='active'
            ).count()
            completed = CampaignLead.query.filter_by(
                campaign_id=campaign.id, status='completed'
            ).count()
            stopped = CampaignLead.query.filter_by(
                campaign_id=campaign.id, status='stopped'
            ).count()

            if active == 0:
                send_telegram_message(
                    f"<b>OUT OF LEADS</b>\n\n"
                    f"Campaign: {campaign.name}\n"
                    f"Active leads: 0\n"
                    f"Completed: {completed}\n"
                    f"Replied/stopped: {stopped}\n\n"
                    f"Add more leads to continue outreach."
                )
            elif active <= 20:
                send_telegram_message(
                    f"<b>Low Leads Warning</b>\n\n"
                    f"Campaign: {campaign.name}\n"
                    f"Active leads remaining: {active}\n"
                    f"Completed: {completed}\n"
                    f"Replied/stopped: {stopped}"
                )

            logger.info(f"Campaign '{campaign.name}': {active} active, {completed} completed, {stopped} stopped")


def check_unreplied_leads():
    """Alert about leads waiting for a human reply — escalated but unanswered."""
    with app.app_context():
        now = datetime.utcnow()

        # Find human-escalated responses where we haven't sent a reply since their message
        escalated = Response.query.filter(
            Response.reviewed == True,
            Response.notes.like('%needs human review%')
        ).order_by(Response.received_at.asc()).all()

        urgent = []     # 48h+
        attention = []  # <48h
        ooo_returned = []

        for resp in escalated:
            lead = resp.lead
            if not lead:
                continue

            # Check if we sent a reply AFTER this response
            replied = SentEmail.query.filter(
                SentEmail.lead_id == lead.id,
                SentEmail.subject.like('Re:%'),
                SentEmail.sent_at >= resp.received_at
            ).first()
            if replied:
                continue

            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            company = lead.company or ''

            hours_waiting = int((now - resp.received_at).total_seconds() / 3600) if resp.received_at else 0

            # Count messages waiting from this lead
            msg_count = Response.query.filter(
                Response.lead_id == lead.id,
                Response.received_at >= resp.received_at
            ).count()

            # Short body summary
            body_hint = (resp.body or '')[:60].strip().replace('\n', ' ')

            entry = {
                'name': name,
                'company': company,
                'hours': hours_waiting,
                'msg_count': msg_count,
                'hint': body_hint,
                'email': lead.email,
            }

            if hours_waiting >= 48:
                urgent.append(entry)
            else:
                attention.append(entry)

        # Check for OOO leads whose return date has passed
        ooo_responses = Response.query.filter(
            Response.notes.like('%OOO_RETURN:%')
        ).all()

        for resp in ooo_responses:
            lead = resp.lead
            if not lead:
                continue
            # Parse return date from notes
            match = re.search(r'OOO_RETURN:(\d{4}-\d{2}-\d{2})', resp.notes or '')
            if not match:
                continue
            try:
                return_date = datetime.strptime(match.group(1), '%Y-%m-%d')
            except ValueError:
                continue

            if return_date > now:
                continue  # not yet returned

            # Check if we re-engaged after return date
            replied = SentEmail.query.filter(
                SentEmail.lead_id == lead.id,
                SentEmail.sent_at >= return_date
            ).first()
            if replied:
                continue

            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            ooo_returned.append({
                'name': name,
                'return_date': match.group(1),
                'email': lead.email,
            })

        # Also check responded leads with no reply at all (not just escalated)
        responded_leads = Lead.query.filter(Lead.status == 'responded').all()
        for lead in responded_leads:
            # Skip if already in our lists
            if any(e['email'] == lead.email for e in urgent + attention):
                continue

            last_response = Response.query.filter_by(lead_id=lead.id).order_by(Response.received_at.desc()).first()
            if not last_response or not last_response.received_at:
                continue

            # Check if we replied after their last message
            replied = SentEmail.query.filter(
                SentEmail.lead_id == lead.id,
                SentEmail.subject.like('Re:%'),
                SentEmail.sent_at >= last_response.received_at
            ).first()
            if replied:
                continue

            hours_waiting = int((now - last_response.received_at).total_seconds() / 3600)
            if hours_waiting < 6:
                continue  # too fresh, AI responder may still handle it

            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            body_hint = (last_response.body or '')[:60].strip().replace('\n', ' ')

            entry = {
                'name': name,
                'company': lead.company or '',
                'hours': hours_waiting,
                'msg_count': 1,
                'hint': body_hint,
                'email': lead.email,
            }
            if hours_waiting >= 48:
                urgent.append(entry)
            else:
                attention.append(entry)

        total = len(urgent) + len(attention) + len(ooo_returned)
        if total == 0:
            logger.info("No unreplied leads to alert about")
            return

        def _esc(s):
            return (s or '').replace('<', '&lt;').replace('>', '&gt;')

        msg = f"📋 <b>UNREPLIED LEADS ({total})</b>\n"

        if urgent:
            msg += "\n<b>🚨 URGENT (48h+)</b>\n"
            for e in sorted(urgent, key=lambda x: -x['hours']):
                line = f"  {_esc(e['name'])}"
                if e['msg_count'] > 1:
                    line += f" | {e['msg_count']} msgs waiting"
                elif e['hint']:
                    line += f" | {_esc(e['hint'][:40])}"
                line += f" | {e['hours']}h"
                msg += line + "\n"

        if attention:
            msg += "\n<b>⏰ NEEDS ATTENTION</b>\n"
            for e in sorted(attention, key=lambda x: -x['hours']):
                line = f"  {_esc(e['name'])}"
                if e['hint']:
                    line += f" | {_esc(e['hint'][:40])}"
                line += f" | {e['hours']}h"
                msg += line + "\n"

        if ooo_returned:
            msg += "\n<b>📅 OOO RETURNED</b>\n"
            for e in ooo_returned:
                msg += f"  {_esc(e['name'])} | back from {e['return_date']} | {e['email']}\n"

        send_telegram_message(msg)
        logger.info(f"Unreplied leads alert sent ({total} leads)")


def check_stale_leads():
    """Detect leads stuck in the pipeline — step 1 only, or stale active."""
    with app.app_context():
        now = datetime.utcnow()
        stale_threshold = now - timedelta(days=7)

        campaigns = Campaign.query.filter_by(status='active').all()

        stuck_step1 = []
        stale_active = []

        for campaign in campaigns:
            sequences = {s.step_number: s for s in campaign.sequences if s.active}
            if not sequences or 1 not in sequences:
                continue

            active_cls = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                status='active'
            ).all()

            for cl in active_cls:
                lead = cl.lead
                if not lead or lead.status in ('responded', 'not_interested', 'signed_up'):
                    continue

                last_sent = SentEmail.query.filter_by(
                    lead_id=lead.id,
                    campaign_id=campaign.id
                ).order_by(SentEmail.sent_at.desc()).first()

                if not last_sent:
                    continue

                step = last_sent.sequence.step_number if last_sent.sequence else 0
                days_since = (now - last_sent.sent_at).days

                # Stuck on step 1: got step 1 but step 2 exists and delay has long passed
                if step == 1 and 2 in sequences:
                    expected_delay = sequences[2].delay_days
                    if days_since > expected_delay + 7:  # 7 days grace period
                        stuck_step1.append({
                            'name': f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                            'email': lead.email,
                            'days': days_since,
                            'campaign': campaign.name,
                        })
                        continue

                # Stale active: no email in 7+ days regardless of step
                if days_since >= 7 and step < max(sequences.keys()):
                    stale_active.append({
                        'name': f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                        'email': lead.email,
                        'days': days_since,
                        'step': step,
                        'campaign': campaign.name,
                    })

        total = len(stuck_step1) + len(stale_active)
        if total == 0:
            logger.info("No stale leads detected")
            return

        def _esc(s):
            return (s or '').replace('<', '&lt;').replace('>', '&gt;')

        msg = f"🔧 <b>STALE PIPELINE ({total} leads)</b>\n"

        if stuck_step1:
            msg += f"\n<b>Stuck after Step 1 ({len(stuck_step1)})</b>\n"
            for e in sorted(stuck_step1, key=lambda x: -x['days'])[:15]:
                msg += f"  {_esc(e['name'])} | {e['days']}d since step 1 | {_esc(e['campaign'])}\n"
            if len(stuck_step1) > 15:
                msg += f"  ...and {len(stuck_step1) - 15} more\n"

        if stale_active:
            msg += f"\n<b>Stale Active ({len(stale_active)})</b>\n"
            for e in sorted(stale_active, key=lambda x: -x['days'])[:15]:
                msg += f"  {_esc(e['name'])} | step {e['step']} | {e['days']}d ago | {_esc(e['campaign'])}\n"
            if len(stale_active) > 15:
                msg += f"  ...and {len(stale_active) - 15} more\n"

        send_telegram_message(msg)
        logger.info(f"Stale leads alert sent ({total} leads)")


def send_daily_summary():
    """Send daily campaign summary with actionable stats."""
    with app.app_context():
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0)
        yesterday_start = today_start - timedelta(days=1)

        campaigns = Campaign.query.filter_by(status='active').all()

        total_sent_today = 0
        total_sent_yesterday = 0
        total_replies_today = 0
        total_replies_yesterday = 0
        total_active = 0
        total_ai_replied = 0
        campaign_lines = []

        for campaign in campaigns:
            active = CampaignLead.query.filter_by(campaign_id=campaign.id, status='active').count()
            stopped = CampaignLead.query.filter_by(campaign_id=campaign.id, status='stopped').count()
            completed = CampaignLead.query.filter_by(campaign_id=campaign.id, status='completed').count()

            sent_today = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= today_start
            ).count()
            sent_yesterday = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= yesterday_start,
                SentEmail.sent_at < today_start
            ).count()

            total_sent = SentEmail.query.filter_by(campaign_id=campaign.id).count()

            campaign_lead_ids = db.session.query(CampaignLead.lead_id).filter_by(
                campaign_id=campaign.id
            ).subquery()

            replies_today = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.received_at >= today_start
            ).count()
            replies_yesterday = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.received_at >= yesterday_start,
                Response.received_at < today_start
            ).count()
            total_responses = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids)
            ).count()

            ai_replied = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.notes.like('%AI auto-replied%')
            ).count()

            total_sent_today += sent_today
            total_sent_yesterday += sent_yesterday
            total_replies_today += replies_today
            total_replies_yesterday += replies_yesterday
            total_active += active
            total_ai_replied += ai_replied

            reply_rate = (total_responses / total_sent * 100) if total_sent > 0 else 0
            campaign_lines.append(
                f"  {campaign.name}: {sent_today} sent, {replies_today} replies, "
                f"{active} active / {stopped} stopped"
            )

        # Reply rate trend
        rate_today = (total_replies_today / total_sent_today * 100) if total_sent_today > 0 else 0
        rate_yesterday = (total_replies_yesterday / total_sent_yesterday * 100) if total_sent_yesterday > 0 else 0
        trend = ''
        if rate_yesterday > 0:
            diff = rate_today - rate_yesterday
            arrow = '📈' if diff > 0 else ('📉' if diff < 0 else '➡️')
            trend = f" {arrow} {diff:+.1f}% vs yesterday"

        # Leads waiting for human reply
        unreplied_names = []
        responded_leads = Lead.query.filter(Lead.status == 'responded').all()
        for lead in responded_leads:
            last_resp = Response.query.filter_by(lead_id=lead.id).order_by(Response.received_at.desc()).first()
            if not last_resp or not last_resp.received_at:
                continue
            replied = SentEmail.query.filter(
                SentEmail.lead_id == lead.id,
                SentEmail.subject.like('Re:%'),
                SentEmail.sent_at >= last_resp.received_at
            ).first()
            if not replied:
                name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
                unreplied_names.append(name)

        # Stale lead counts
        stale_count = 0
        step1_stuck = 0
        for campaign in campaigns:
            sequences = {s.step_number: s for s in campaign.sequences if s.active}
            if not sequences or 1 not in sequences:
                continue
            active_cls = CampaignLead.query.filter_by(campaign_id=campaign.id, status='active').all()
            for cl in active_cls:
                lead = cl.lead
                if not lead or lead.status in ('responded', 'not_interested', 'signed_up'):
                    continue
                last_sent = SentEmail.query.filter_by(
                    lead_id=lead.id, campaign_id=campaign.id
                ).order_by(SentEmail.sent_at.desc()).first()
                if not last_sent:
                    continue
                step = last_sent.sequence.step_number if last_sent.sequence else 0
                days_since = (now - last_sent.sent_at).days
                if step == 1 and 2 in sequences and days_since > sequences[2].delay_days + 7:
                    step1_stuck += 1
                elif days_since >= 7 and step < max(sequences.keys()):
                    stale_count += 1

        # Expected sends tomorrow (same as today's capacity minus sent)
        daily_cap = int(os.environ.get('DAILY_SEND_CAP', '25'))

        def _esc(s):
            return (s or '').replace('<', '&lt;').replace('>', '&gt;')

        msg = (
            f"📊 <b>DAILY SUMMARY</b>\n"
            f"{now.strftime('%b %d, %Y')}\n"
            f"{'─'*22}\n\n"
            f"<b>TODAY</b>\n"
            f"  Sent: {total_sent_today} | Replies: {total_replies_today}\n"
            f"  Reply rate: {rate_today:.1f}%{trend}\n"
            f"  AI auto-replied: {total_ai_replied}\n\n"
        )

        if campaign_lines:
            msg += "<b>CAMPAIGNS</b>\n"
            msg += "\n".join(campaign_lines) + "\n\n"

        if unreplied_names:
            msg += f"<b>⏳ WAITING FOR YOUR REPLY ({len(unreplied_names)})</b>\n"
            for n in unreplied_names[:5]:
                msg += f"  {_esc(n)}\n"
            if len(unreplied_names) > 5:
                msg += f"  ...and {len(unreplied_names) - 5} more\n"
            msg += "\n"

        # Pipeline health
        pipeline_issues = []
        if step1_stuck > 0:
            pipeline_issues.append(f"{step1_stuck} stuck after step 1")
        if stale_count > 0:
            pipeline_issues.append(f"{stale_count} stale (7d+ no email)")

        msg += "<b>PIPELINE</b>\n"
        msg += f"  Active leads: {total_active}\n"
        msg += f"  Tomorrow's capacity: ~{daily_cap} emails\n"
        if pipeline_issues:
            msg += f"  ⚠️ Issues: {', '.join(pipeline_issues)}\n"

        send_telegram_message(msg)
        logger.info("Daily summary sent")


def send_weekly_digest():
    """Send comprehensive weekly report — designed for Sunday evenings."""
    with app.app_context():
        now = datetime.utcnow()
        week_start = now - timedelta(days=7)
        prev_week_start = now - timedelta(days=14)

        campaigns = Campaign.query.filter_by(status='active').all()

        # --- Aggregate stats across all campaigns ---
        total_sent_week = 0
        total_sent_prev = 0
        total_sent_alltime = 0
        total_replies_week = 0
        total_replies_prev = 0
        total_replies_alltime = 0
        total_ai_replied = 0
        total_active_leads = 0
        total_stopped = 0
        total_completed = 0
        campaign_blocks = []

        for campaign in campaigns:
            active = CampaignLead.query.filter_by(campaign_id=campaign.id, status='active').count()
            completed = CampaignLead.query.filter_by(campaign_id=campaign.id, status='completed').count()
            stopped = CampaignLead.query.filter_by(campaign_id=campaign.id, status='stopped').count()

            sent_week = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= week_start
            ).count()
            sent_prev = SentEmail.query.filter(
                SentEmail.campaign_id == campaign.id,
                SentEmail.sent_at >= prev_week_start,
                SentEmail.sent_at < week_start
            ).count()
            sent_alltime = SentEmail.query.filter_by(campaign_id=campaign.id).count()

            campaign_lead_ids = db.session.query(CampaignLead.lead_id).filter_by(
                campaign_id=campaign.id
            ).subquery()

            replies_week = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.received_at >= week_start
            ).count()
            replies_prev = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.received_at >= prev_week_start,
                Response.received_at < week_start
            ).count()
            replies_alltime = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids)
            ).count()

            ai_replied = Response.query.filter(
                Response.lead_id.in_(campaign_lead_ids),
                Response.notes.like('%AI auto-replied%')
            ).count()

            week_rate = (replies_week / sent_week * 100) if sent_week > 0 else 0

            total_sent_week += sent_week
            total_sent_prev += sent_prev
            total_sent_alltime += sent_alltime
            total_replies_week += replies_week
            total_replies_prev += replies_prev
            total_replies_alltime += replies_alltime
            total_ai_replied += ai_replied
            total_active_leads += active
            total_stopped += stopped
            total_completed += completed

            campaign_blocks.append(
                f"<b>{campaign.name}</b>\n"
                f"  Sent: {sent_week} | Replies: {replies_week}"
                + (f" ({week_rate:.1f}%)" if sent_week > 0 else "") + "\n"
                f"  Leads: {active} active / {stopped} replied / {completed} done"
            )

        # --- Conversion funnel ---
        # signed_up = leads that went from contacted -> signed_up
        signed_up_count = Lead.query.filter(Lead.status == 'signed_up').count()

        overall_rate = (total_replies_alltime / total_sent_alltime * 100) if total_sent_alltime > 0 else 0
        week_rate = (total_replies_week / total_sent_week * 100) if total_sent_week > 0 else 0
        prev_rate = (total_replies_prev / total_sent_prev * 100) if total_sent_prev > 0 else 0

        rate_trend = ''
        if prev_rate > 0:
            diff = week_rate - prev_rate
            arrow = '📈' if diff > 0 else ('📉' if diff < 0 else '➡️')
            rate_trend = f" {arrow} {diff:+.1f}% vs last week"

        # --- Estimated days until leads exhausted ---
        if total_sent_week > 0:
            daily_rate = total_sent_week / 7
            days_remaining = int(total_active_leads / daily_rate) if daily_rate > 0 else 999
            runway = f"~{days_remaining} days"
            depletion_date = (now + timedelta(days=days_remaining)).strftime('%b %d')
            runway += f" (depletes ~{depletion_date})"
        else:
            runway = "N/A (no sends this week)"

        # --- Top responding leads this week ---
        recent_responses = Response.query.filter(
            Response.received_at >= week_start
        ).order_by(Response.received_at.desc()).all()

        # Deduplicate by lead and get their context
        seen_leads = set()
        top_responders = []
        for resp in recent_responses:
            lead = resp.lead
            if not lead or lead.id in seen_leads:
                continue
            seen_leads.add(lead.id)

            name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            name = name.replace('<', '&lt;').replace('>', '&gt;')

            # Brief context from their message
            hint = (resp.body or '')[:50].strip().replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;')

            status_tag = ""
            if resp.notes and "AI auto-replied" in resp.notes:
                status_tag = " [AI handled]"
            elif resp.notes and "needs human review" in resp.notes:
                status_tag = " [needs reply]"
            elif resp.reviewed:
                status_tag = " [reviewed]"
            top_responders.append(f"  {name}{status_tag}")
            if len(top_responders) >= 8:
                break

        # --- Leads at risk ---
        at_risk = []
        # Unreplied escalated
        escalated = Response.query.filter(
            Response.reviewed == True,
            Response.notes.like('%needs human review%')
        ).all()
        for resp in escalated:
            lead = resp.lead
            if not lead or not resp.received_at:
                continue
            replied = SentEmail.query.filter(
                SentEmail.lead_id == lead.id,
                SentEmail.subject.like('Re:%'),
                SentEmail.sent_at >= resp.received_at
            ).first()
            if not replied:
                name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
                hours = int((now - resp.received_at).total_seconds() / 3600)
                at_risk.append(f"  {name} — unreplied {hours}h")

        # OOO expired
        ooo_responses = Response.query.filter(
            Response.notes.like('%OOO_RETURN:%')
        ).all()
        for resp in ooo_responses:
            lead = resp.lead
            if not lead:
                continue
            match = re.search(r'OOO_RETURN:(\d{4}-\d{2}-\d{2})', resp.notes or '')
            if not match:
                continue
            try:
                return_date = datetime.strptime(match.group(1), '%Y-%m-%d')
            except ValueError:
                continue
            if return_date <= now:
                replied = SentEmail.query.filter(
                    SentEmail.lead_id == lead.id,
                    SentEmail.sent_at >= return_date
                ).first()
                if not replied:
                    name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
                    at_risk.append(f"  {name} — OOO returned {match.group(1)}")

        # --- Build the digest ---
        msg = (
            f"📋 <b>WEEKLY DIGEST</b>\n"
            f"{now.strftime('%b %d, %Y')}\n"
            f"{'─'*25}\n\n"
            f"<b>CONVERSION FUNNEL</b>\n"
            f"  Sent: {total_sent_alltime} → Replied: {total_replies_alltime} ({overall_rate:.1f}%) → Signed up: {signed_up_count}\n\n"
            f"<b>THIS WEEK</b>\n"
            f"  Emails sent: {total_sent_week}\n"
            f"  Replies: {total_replies_week} ({week_rate:.1f}%){rate_trend}\n"
            f"  AI auto-replied: {total_ai_replied}\n\n"
            f"<b>PIPELINE</b>\n"
            f"  Active leads: {total_active_leads}\n"
            f"  Lead runway: {runway}\n\n"
        )

        if campaign_blocks:
            msg += "<b>BY CAMPAIGN</b>\n"
            msg += "\n".join(campaign_blocks)
            msg += "\n\n"

        if top_responders:
            msg += "<b>TOP RESPONDERS</b>\n"
            msg += "\n".join(top_responders[:8])
            msg += "\n\n"

        if at_risk:
            msg += f"<b>⚠️ LEADS AT RISK ({len(at_risk)})</b>\n"
            msg += "\n".join(at_risk[:10])
            if len(at_risk) > 10:
                msg += f"\n  ...and {len(at_risk) - 10} more"
            msg += "\n"

        send_telegram_message(msg)
        logger.info("Weekly digest sent")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Telegram Notifier')
    parser.add_argument('--once', action='store_true', help='Check new responses once')
    parser.add_argument('--test', action='store_true', help='Send test notification')
    parser.add_argument('--leads', action='store_true', help='Check lead status')
    parser.add_argument('--summary', action='store_true', help='Send daily summary')
    parser.add_argument('--weekly', action='store_true', help='Send weekly digest')
    parser.add_argument('--unreplied', action='store_true', help='Check unreplied leads')
    parser.add_argument('--stale', action='store_true', help='Check stale pipeline leads')
    parser.add_argument('--all', action='store_true', help='Run all checks')

    args = parser.parse_args()

    if args.test:
        if send_telegram_message("<b>Test notification</b>\n\nWedding Counselors notifications are working."):
            print("Test notification sent.")
        else:
            print("Failed to send. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        sys.exit(0)

    if args.weekly:
        send_weekly_digest()
        print("Weekly digest sent.")
        sys.exit(0)

    if args.summary:
        send_daily_summary()
        print("Daily summary sent.")
        sys.exit(0)

    if args.unreplied:
        check_unreplied_leads()
        print("Unreplied leads check complete.")
        sys.exit(0)

    if args.stale:
        check_stale_leads()
        print("Stale leads check complete.")
        sys.exit(0)

    if args.all:
        check_new_responses()
        check_lead_status()
        check_unreplied_leads()
        check_stale_leads()
        print("All checks complete.")
    elif args.leads:
        check_lead_status()
        print("Lead status check complete.")
    else:
        check_new_responses()
        print("Response check complete.")
