#!/usr/bin/env python3
"""Remove the invalid sample inbox and reassign campaigns"""

from app import app, db
from models import Inbox, Campaign

with app.app_context():
    # Find the sample inbox
    sample = Inbox.query.filter_by(email="sales@ratetapmx.com").first()

    if sample:
        # Find a valid inbox to reassign campaigns to
        valid_inbox = Inbox.query.filter(Inbox.email != "sales@ratetapmx.com").first()

        if valid_inbox:
            # Reassign any campaigns using the sample inbox
            campaigns = Campaign.query.filter_by(inbox_id=sample.id).all()
            for campaign in campaigns:
                print(f"Reassigning campaign '{campaign.name}' to {valid_inbox.email}")
                campaign.inbox_id = valid_inbox.id

            db.session.commit()

            # Now delete the sample inbox
            db.session.delete(sample)
            db.session.commit()
            print("✓ Removed invalid sample inbox (sales@ratetapmx.com)")
        else:
            print("Error: No valid inbox found to reassign campaigns")
    else:
        print("Sample inbox not found (already removed)")

    # Show remaining inboxes
    print("\nActive inboxes:")
    for inbox in Inbox.query.all():
        status = "active" if inbox.active else "inactive"
        print(f"  - {inbox.email} ({status})")
