#!/usr/bin/env python3
"""
CRM Tracking Dashboard - Run anytime to check system status

Usage: python track.py
"""

from app import app, db
from datetime import datetime, timedelta, UTC
import pytz

def main():
    tz = pytz.timezone('America/Mexico_City')
    now = datetime.now(tz)

    print('='*60)
    print('EMAIL CRM - TRACKING DASHBOARD')
    print('='*60)
    print()
    print(f'Time (Mexico City): {now.strftime("%Y-%m-%d %H:%M:%S")}')
    in_window = 9 <= now.hour < 17
    print(f'Sending Window: 9 AM - 5 PM | Currently: {"✓ IN WINDOW" if in_window else "✗ OUTSIDE"}')
    print()

    with app.app_context():
        from models import Campaign, Lead, SentEmail, Sequence, CampaignLead, Inbox, Response

        campaigns = Campaign.query.all()

        for campaign in campaigns:
            status_icon = "●" if campaign.status == 'active' else "○"
            print(f'{status_icon} CAMPAIGN: {campaign.name} [{campaign.status.upper()}]')
            print('-'*60)

            # Sequences
            seqs = Sequence.query.filter_by(campaign_id=campaign.id).order_by(Sequence.step_number).all()
            print('Sequence Schedule:')
            for seq in seqs:
                print(f'  Step {seq.step_number}: +{seq.delay_days} days - "{seq.subject_template}"')
            print()

            # Lead tracking
            print('LEAD STATUS:')
            campaign_leads = CampaignLead.query.filter_by(campaign_id=campaign.id).all()

            for cl in campaign_leads:
                lead = db.session.get(Lead, cl.lead_id)
                sent_emails = SentEmail.query.filter_by(
                    lead_id=lead.id,
                    campaign_id=campaign.id
                ).order_by(SentEmail.sequence_id).all()

                # Status emoji
                status_emoji = {"active": "📧", "responded": "✅", "stopped": "⏹", "completed": "🏁"}.get(cl.status, "❓")

                print(f'{status_emoji} {lead.first_name} {lead.last_name} <{lead.email}>')
                print(f'   Company: {lead.company} | Status: {cl.status}')

                # Sent emails
                for se in sent_emails:
                    seq = db.session.get(Sequence, se.sequence_id)
                    inbox = db.session.get(Inbox, se.inbox_id)
                    status_mark = "✓" if se.status == 'sent' else "✗"
                    print(f'   [{status_mark}] Step {seq.step_number} sent {se.sent_at.strftime("%m/%d %H:%M")} via {inbox.name}')

                # Pending steps
                sent_steps = {db.session.get(Sequence, se.sequence_id).step_number for se in sent_emails}
                for seq in seqs:
                    if seq.step_number not in sent_steps:
                        if sent_emails:
                            last_sent = sent_emails[-1].sent_at
                            next_send = last_sent + timedelta(days=seq.delay_days)
                            days_until = (next_send - datetime.now(UTC).replace(tzinfo=None)).days
                            print(f'   [ ] Step {seq.step_number} in ~{max(0, days_until)} days')
                        else:
                            print(f'   [ ] Step {seq.step_number} pending')
                print()

        # Summary
        total_sent = SentEmail.query.count()
        total_failed = SentEmail.query.filter_by(status='failed').count()
        total_bounced = SentEmail.query.filter_by(status='bounced').count()
        total_responses = Response.query.count()

        print('='*60)
        print('SUMMARY')
        print('='*60)
        print(f'Emails Sent:     {total_sent}')
        print(f'Failed:          {total_failed}')
        print(f'Bounced:         {total_bounced}')
        print(f'Responses:       {total_responses}')
        print(f'Response Rate:   {(total_responses/total_sent*100) if total_sent > 0 else 0:.1f}%')
        print()

        # Inbox capacity
        print('INBOX STATUS:')
        inboxes = Inbox.query.filter_by(active=True).all()
        for inbox in inboxes:
            hour_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
            sent_last_hour = SentEmail.query.filter(
                SentEmail.inbox_id == inbox.id,
                SentEmail.sent_at >= hour_ago
            ).count()
            capacity = f'{sent_last_hour}/{inbox.max_per_hour}'
            bar = '█' * sent_last_hour + '░' * (inbox.max_per_hour - sent_last_hour)
            print(f'  {inbox.name}: [{bar}] {capacity}')
        print()

        # Scheduler info
        print('AUTOMATION:')
        print('  ✓ Email sending:    Every 60 min (during 9 AM - 5 PM)')
        print('  ✓ Response check:   Every 10 min')
        print('  ✓ AI auto-reply:    Every 15 min')
        print('  ✓ Lead prospecting: 9 AM & 3 PM daily')
        print()


if __name__ == '__main__':
    main()
