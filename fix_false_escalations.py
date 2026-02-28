#!/usr/bin/env python3
"""
One-shot fix: Re-queue responses that were falsely escalated due to missing API key.

When OPENROUTER_API_KEY was missing, the AI responder couldn't analyze intent,
so confidence was 0.0 and all responses got escalated as "needs human review".
Now that the key is fixed, re-queue these for proper AI analysis.

Only re-queues responses where:
  - reviewed=True
  - notes contains "confidence=0" (the signature of no-API-key failure)
  - No Re: reply has been sent since their message

Run via: GitHub Actions → "Force Process Pending Replies" workflow_dispatch
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

from app import app
from models import db, Response, SentEmail


def main():
    print("Fixing false escalations from missing API key...\n")

    with app.app_context():
        # Find responses that were escalated with 0 confidence (API key was missing)
        false_escalations = Response.query.filter(
            Response.reviewed == True,
            Response.notes.like('%confidence=0%')
        ).all()

        requeued = 0
        skipped = 0

        for resp in false_escalations:
            lead = resp.lead
            if not lead:
                continue

            # Check if a human already replied
            already_replied = SentEmail.query.filter(
                SentEmail.lead_id == lead.id,
                SentEmail.subject.like('Re:%'),
                SentEmail.sent_at >= resp.received_at
            ).first()

            if already_replied:
                print(f"  SKIP: {lead.email} — already replied to")
                skipped += 1
                continue

            # Re-queue for AI processing
            resp.reviewed = False
            resp.notified = False
            resp.notes = "Re-queued: was falsely escalated due to missing API key"
            db.session.commit()
            requeued += 1
            print(f"  RE-QUEUED: {lead.email} (was: {resp.notes})")

        print(f"\nTotal re-queued: {requeued}, skipped (already replied): {skipped}")
        print("Run 'Force Process Pending Replies' workflow to process these.")


if __name__ == "__main__":
    main()
