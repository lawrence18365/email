#!/usr/bin/env python3
"""
Pause underperforming campaigns B, C, D and reassign their active leads to Campaign A.

Campaign A ("Social Proof") has 10-55% reply rates.
Campaigns B, C, D have 0% reply rates on Step 1 subjects.

This script:
1. Pauses campaigns B, C, D (sets status='paused')
2. Reassigns active leads from B/C/D to Campaign A
3. Resets reassigned leads to Step 1 of Campaign A
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import app
from models import db, Campaign, CampaignLead, SentEmail

def main():
    with app.app_context():
        # Find campaigns by name pattern
        campaigns = Campaign.query.filter_by(status='active').all()

        campaign_a = None
        campaigns_to_pause = []

        for c in campaigns:
            name = c.name or ''
            if '[A]' in name or 'Social Proof' in name:
                campaign_a = c
                print(f"Campaign A (KEEP): #{c.id} — {c.name}")
            elif '[B]' in name or 'Variant C' in name or 'Variant D' in name or 'Authority' in name or 'Reciprocity' in name or 'Google Visibility' in name or 'Free Profile' in name:
                campaigns_to_pause.append(c)
                print(f"Campaign to PAUSE: #{c.id} — {c.name}")
            else:
                print(f"Campaign (unchanged): #{c.id} — {c.name}")

        if not campaign_a:
            print("ERROR: Could not find Campaign A (Social Proof). Aborting.")
            return

        if not campaigns_to_pause:
            print("No underperforming campaigns found (already paused or don't exist). Done.")
            return

        # Count active leads in each campaign to pause
        total_reassigned = 0
        total_already_in_a = 0
        total_skipped_responded = 0

        for c in campaigns_to_pause:
            active_leads = CampaignLead.query.filter_by(
                campaign_id=c.id,
                status='active'
            ).all()

            print(f"\n  Campaign #{c.id} ({c.name}): {len(active_leads)} active leads")

            for cl in active_leads:
                lead = cl.lead

                # Skip leads who already responded or signed up
                if lead.status in ('responded', 'signed_up', 'not_interested', 'bounced'):
                    cl.status = 'stopped'
                    total_skipped_responded += 1
                    continue

                # Check if this lead is already in Campaign A
                existing_in_a = CampaignLead.query.filter_by(
                    lead_id=cl.lead_id,
                    campaign_id=campaign_a.id
                ).first()

                if existing_in_a:
                    # Already in A — just stop the B/C/D entry
                    cl.status = 'stopped'
                    total_already_in_a += 1
                else:
                    # Check if this lead has already received emails from their current campaign
                    sent_count = SentEmail.query.filter_by(
                        lead_id=cl.lead_id,
                        campaign_id=c.id
                    ).count()

                    # Add to Campaign A as active
                    new_cl = CampaignLead(
                        campaign_id=campaign_a.id,
                        lead_id=cl.lead_id,
                        status='active'
                    )
                    db.session.add(new_cl)

                    # Stop in old campaign
                    cl.status = 'stopped'
                    total_reassigned += 1

            # Pause the campaign
            c.status = 'paused'
            print(f"  -> Paused campaign #{c.id}")

        db.session.commit()

        print(f"\n{'='*50}")
        print(f"DONE")
        print(f"  Reassigned to Campaign A: {total_reassigned}")
        print(f"  Already in Campaign A: {total_already_in_a}")
        print(f"  Skipped (responded/signed up): {total_skipped_responded}")
        print(f"  Campaigns paused: {len(campaigns_to_pause)}")


if __name__ == '__main__':
    main()
