#!/usr/bin/env python3
"""
Supabase Signup Sync — runs before outreach emails in the cron pipeline.

Checks every active/contacted lead against the Supabase website database.
If they already signed up, marks them as 'signed_up' and stops their campaign.

This prevents double-outreach to people who are already on the platform.
"""
import os
import sys
import logging

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from app import app, _ensure_response_columns
from models import db, Lead, CampaignLead

with app.app_context():
    _ensure_response_columns()


def sync():
    """Sync Supabase signups -> CRM lead statuses."""
    url = os.environ.get('SUPABASE_URL', '')
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if not url or not key:
        logger.warning("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — skipping sync")
        return 0

    try:
        from supabase import create_client
        sb = create_client(url, key)
    except Exception as e:
        logger.error(f"Could not create Supabase client: {e}")
        return 0

    updated = 0

    with app.app_context():
        # Get all leads that could potentially be on the website
        leads = Lead.query.filter(
            Lead.status.in_(['new', 'contacted', 'responded'])
        ).all()
        logger.info(f"Checking {len(leads)} leads against Supabase signups")

        for lead in leads:
            try:
                # Check profiles table
                result = sb.table("profiles").select("id, is_claimed").ilike("email", lead.email.strip()).execute()
                if result.data:
                    claimed = result.data[0].get("is_claimed", False)
                    logger.info(f"SYNC: {lead.email} signed up (claimed={claimed}) — updating from '{lead.status}'")
                    lead.status = 'signed_up'

                    # Stop all active campaigns for this lead
                    active_cls = CampaignLead.query.filter_by(lead_id=lead.id, status='active').all()
                    for cl in active_cls:
                        cl.status = 'completed'

                    db.session.commit()
                    updated += 1
                    continue

                # Also check auth.users
                result2 = sb.schema("auth").from_("users").select("id").ilike("email", lead.email.strip()).execute()
                if result2.data:
                    logger.info(f"SYNC: {lead.email} has auth account — updating from '{lead.status}'")
                    lead.status = 'signed_up'

                    active_cls = CampaignLead.query.filter_by(lead_id=lead.id, status='active').all()
                    for cl in active_cls:
                        cl.status = 'completed'

                    db.session.commit()
                    updated += 1

            except Exception as e:
                logger.warning(f"Supabase check failed for {lead.email}: {e}")
                continue

    logger.info(f"Signup sync complete: {updated} leads updated to 'signed_up'")
    return updated


if __name__ == "__main__":
    count = sync()
    print(f"Done — {count} leads synced")
