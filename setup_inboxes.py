#!/usr/bin/env python3
"""Add RateTapMX email inboxes to CRM"""

from app import app, db
from models import Inbox

inboxes = [
    {
        "name": "Camila",
        "email": "camila@ratetapmx.com",
        "username": "camila@ratetapmx.com",
        "password": "z7bP=00j",
    },
    {
        "name": "Madison",
        "email": "madison@ratetapmx.com",
        "username": "madison@ratetapmx.com",
        "password": "kysq0>oH",
    },
    {
        "name": "Valeria",
        "email": "valeria@ratetapmx.com",
        "username": "valeria@ratetapmx.com",
        "password": "5$u0s32S",
    },
]

with app.app_context():
    for inbox_data in inboxes:
        # Check if exists
        existing = Inbox.query.filter_by(email=inbox_data["email"]).first()
        if existing:
            print(f"Updating: {inbox_data['email']}")
            existing.username = inbox_data["username"]
            existing.password = inbox_data["password"]
            existing.smtp_host = "mail.spacemail.com"
            existing.smtp_port = 465
            existing.smtp_use_tls = False  # Using SSL on 465
            existing.imap_host = "mail.spacemail.com"
            existing.imap_port = 993
            existing.imap_use_ssl = True
            existing.active = True
            existing.max_per_hour = 5
        else:
            print(f"Adding: {inbox_data['email']}")
            inbox = Inbox(
                name=inbox_data["name"],
                email=inbox_data["email"],
                username=inbox_data["username"],
                password=inbox_data["password"],
                smtp_host="mail.spacemail.com",
                smtp_port=465,
                smtp_use_tls=False,  # SSL on 465
                imap_host="mail.spacemail.com",
                imap_port=993,
                imap_use_ssl=True,
                active=True,
                max_per_hour=5
            )
            db.session.add(inbox)

    db.session.commit()
    print("\n✓ All inboxes configured!")

    # List all inboxes
    print("\nConfigured inboxes:")
    for inbox in Inbox.query.all():
        print(f"  - {inbox.email} (max {inbox.max_per_hour}/hour)")
