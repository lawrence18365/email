#!/usr/bin/env python3
"""
One-time script: Pause underperforming campaigns and reassign their
active leads to the best-performing campaign.

Safe to call repeatedly — exits instantly once the work is already done.
"""

import os
import sys
import logging

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# IDs of campaigns that showed 0 % reply rate during the initial A/B test
UNDERPERFORMER_IDS = [2, 4]  # Campaign B, Campaign D
TARGET_CAMPAIGN_ID = 1        # Campaign A (best performer)


def main():
    """Pause underperformers and move their active leads to the target campaign."""
    from models import db, Campaign, CampaignLead

    # Quick exit: if all underperformers are already paused with 0 active leads, nothing to do
    need_work = False
    for cid in UNDERPERFORMER_IDS:
        campaign = Campaign.query.get(cid)
        if not campaign:
            continue
        if campaign.status == 'active':
            need_work = True
            break
        active_leads = CampaignLead.query.filter_by(campaign_id=cid, status='active').count()
        if active_leads > 0:
            need_work = True
            break

    if not need_work:
        return  # Already done — silent exit

    target = Campaign.query.get(TARGET_CAMPAIGN_ID)
    if not target:
        logger.error(f"Target campaign {TARGET_CAMPAIGN_ID} not found, aborting")
        return

    moved = 0
    for cid in UNDERPERFORMER_IDS:
        campaign = Campaign.query.get(cid)
        if not campaign:
            continue

        # Pause the campaign
        if campaign.status != 'paused':
            campaign.status = 'paused'
            logger.info(f"Paused campaign {cid} ({campaign.name})")

        # Move remaining active leads to the target campaign
        active_cls = CampaignLead.query.filter_by(campaign_id=cid, status='active').all()
        for cl in active_cls:
            # Check if lead is already in the target campaign
            existing = CampaignLead.query.filter_by(
                campaign_id=TARGET_CAMPAIGN_ID,
                lead_id=cl.lead_id
            ).first()
            if existing:
                cl.status = 'stopped'
            else:
                cl.campaign_id = TARGET_CAMPAIGN_ID
                moved += 1

    db.session.commit()
    if moved:
        logger.info(f"Moved {moved} active lead(s) to campaign {TARGET_CAMPAIGN_ID}")


if __name__ == '__main__':
    from app import app
    with app.app_context():
        main()
