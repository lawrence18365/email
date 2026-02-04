#!/usr/bin/env python3
"""
A/B Test Results Tracker
Shows comparative stats between campaign variants.
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

from app import app
from models import db, Campaign, CampaignLead, SentEmail, Response


def get_campaign_stats(campaign):
    """Get stats for a single campaign."""
    active = CampaignLead.query.filter_by(campaign_id=campaign.id, status='active').count()
    completed = CampaignLead.query.filter_by(campaign_id=campaign.id, status='completed').count()
    stopped = CampaignLead.query.filter_by(campaign_id=campaign.id, status='stopped').count()

    total_leads = active + completed + stopped

    # Emails sent
    emails_sent = SentEmail.query.filter_by(campaign_id=campaign.id).count()

    # Unique leads contacted
    unique_contacted = db.session.query(SentEmail.lead_id).filter_by(
        campaign_id=campaign.id
    ).distinct().count()

    # Responses
    responses = db.session.query(Response).join(SentEmail).filter(
        SentEmail.campaign_id == campaign.id
    ).count()

    # Reply rate
    reply_rate = (responses / unique_contacted * 100) if unique_contacted > 0 else 0

    return {
        'name': campaign.name,
        'total_leads': total_leads,
        'active': active,
        'completed': completed,
        'stopped': stopped,
        'emails_sent': emails_sent,
        'unique_contacted': unique_contacted,
        'responses': responses,
        'reply_rate': reply_rate
    }


def print_comparison():
    """Print side-by-side comparison of A/B test campaigns."""
    with app.app_context():
        campaigns = Campaign.query.filter(
            Campaign.name.like('%Wedding Counselors%')
        ).all()

        if len(campaigns) < 2:
            print("Need at least 2 campaigns for A/B comparison")
            return

        stats = [get_campaign_stats(c) for c in campaigns]

        # Sort by name to get A before B
        stats.sort(key=lambda x: x['name'])

        print("\n" + "=" * 60)
        print("A/B TEST RESULTS")
        print("=" * 60)

        # Header
        print(f"\n{'Metric':<25} {'Version A':<15} {'Version B':<15}")
        print("-" * 55)

        # Stats
        metrics = [
            ('Total Leads', 'total_leads'),
            ('Contacted', 'unique_contacted'),
            ('Emails Sent', 'emails_sent'),
            ('Replies', 'responses'),
            ('Reply Rate', 'reply_rate'),
            ('Remaining', 'active'),
        ]

        for label, key in metrics:
            val_a = stats[0][key]
            val_b = stats[1][key]

            if key == 'reply_rate':
                print(f"{label:<25} {val_a:>13.1f}% {val_b:>13.1f}%")
                # Highlight winner
                if val_a > val_b and stats[0]['unique_contacted'] >= 20:
                    print(f"{'  → Version A winning':<25}")
                elif val_b > val_a and stats[1]['unique_contacted'] >= 20:
                    print(f"{'  → Version B winning':<25}")
            else:
                print(f"{label:<25} {val_a:>14} {val_b:>14}")

        print("\n" + "-" * 55)
        print("Version A:", stats[0]['name'])
        print("Version B:", stats[1]['name'])

        # Statistical significance note
        total_contacted = stats[0]['unique_contacted'] + stats[1]['unique_contacted']
        if total_contacted < 100:
            print(f"\n⚠️  Sample size too small ({total_contacted} contacted)")
            print("   Need ~100+ per variant for reliable results")
        elif total_contacted < 200:
            print(f"\n📊 Early results ({total_contacted} contacted)")
            print("   Continue testing for more confidence")
        else:
            print(f"\n✅ Good sample size ({total_contacted} contacted)")
            print("   Results are becoming statistically meaningful")


def send_telegram_report():
    """Send A/B test results to Telegram."""
    from telegram_notifier import send_telegram_message

    with app.app_context():
        campaigns = Campaign.query.filter(
            Campaign.name.like('%Wedding Counselors%')
        ).all()

        if len(campaigns) < 2:
            return

        stats = [get_campaign_stats(c) for c in campaigns]
        stats.sort(key=lambda x: x['name'])

        a, b = stats[0], stats[1]

        winner = ""
        if a['reply_rate'] > b['reply_rate'] and a['unique_contacted'] >= 20:
            winner = "\n\n🏆 <b>Version A winning!</b>"
        elif b['reply_rate'] > a['reply_rate'] and b['unique_contacted'] >= 20:
            winner = "\n\n🏆 <b>Version B winning!</b>"

        msg = f"""📊 <b>A/B Test Update</b>

<b>Version A</b> (Social Proof)
Contacted: {a['unique_contacted']} | Replies: {a['responses']} | Rate: {a['reply_rate']:.1f}%

<b>Version B</b> (Pain Point)
Contacted: {b['unique_contacted']} | Replies: {b['responses']} | Rate: {b['reply_rate']:.1f}%{winner}"""

        send_telegram_message(msg)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='A/B Test Results')
    parser.add_argument('--telegram', action='store_true', help='Send results to Telegram')

    args = parser.parse_args()

    if args.telegram:
        send_telegram_report()
        print("Results sent to Telegram")
    else:
        print_comparison()
