#!/usr/bin/env python3
"""
Database initialization script for RateTapMX CRM

Usage:
    python init_db.py              # Initialize database
    python init_db.py --sample     # Initialize with sample data
"""

import sys
import argparse
from app import app, db
from models import Lead, Campaign, Sequence, Inbox, SentEmail, Response, CampaignLead


def init_database():
    """Create all database tables"""
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Database tables created successfully!")


def add_sample_data():
    """Add sample data for testing"""
    with app.app_context():
        print("Adding sample data...")

        # Check if data already exists
        if Inbox.query.first():
            print("Sample data already exists. Skipping.")
            return

        # Add sample inbox
        inbox = Inbox(
            name="Sales Team",
            email="sales@ratetapmx.com",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_use_tls=True,
            imap_host="imap.gmail.com",
            imap_port=993,
            imap_use_ssl=True,
            username="sales@ratetapmx.com",
            password="your-app-password-here",
            max_per_hour=5,
            active=True
        )
        db.session.add(inbox)
        db.session.commit()
        print(f"✓ Added inbox: {inbox.email}")

        # Add sample leads
        sample_leads = [
            {
                "email": "john@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "company": "Acme Inc",
                "website": "https://acme.com",
                "status": "new",
                "source": "manual"
            },
            {
                "email": "jane@test.com",
                "first_name": "Jane",
                "last_name": "Smith",
                "company": "Test Corp",
                "website": "https://test.com",
                "status": "new",
                "source": "manual"
            },
            {
                "email": "bob@demo.com",
                "first_name": "Bob",
                "last_name": "Johnson",
                "company": "Demo LLC",
                "website": "https://demo.com",
                "status": "new",
                "source": "manual"
            }
        ]

        leads = []
        for lead_data in sample_leads:
            lead = Lead(**lead_data)
            db.session.add(lead)
            leads.append(lead)

        db.session.commit()
        print(f"✓ Added {len(leads)} sample leads")

        # Add sample campaign
        campaign = Campaign(
            name="Introduction Campaign",
            inbox_id=inbox.id,
            status="draft"
        )
        db.session.add(campaign)
        db.session.commit()
        print(f"✓ Added campaign: {campaign.name}")

        # Add sample sequences
        sequences = [
            {
                "campaign_id": campaign.id,
                "step_number": 1,
                "delay_days": 0,
                "subject_template": "Quick question about {company}",
                "email_template": """Hi {firstName},

I came across {company} and was impressed by your work in the industry.

I wanted to reach out because we help companies like yours streamline their operations with our platform at RateTapMX.

Would you be open to a quick 15-minute call this week to discuss how we might be able to help {company}?

Best regards,
Sales Team
RateTapMX"""
            },
            {
                "campaign_id": campaign.id,
                "step_number": 2,
                "delay_days": 3,
                "subject_template": "Following up - {company}",
                "email_template": """Hi {firstName},

I wanted to follow up on my previous email about how RateTapMX can help {company}.

I know you're busy, but I believe we could add significant value to your operations.

Are you available for a brief call this week?

Best regards,
Sales Team
RateTapMX"""
            },
            {
                "campaign_id": campaign.id,
                "step_number": 3,
                "delay_days": 7,
                "subject_template": "Last attempt - opportunity for {company}",
                "email_template": """Hi {firstName},

This is my last email - I don't want to be a pest!

I truly believe RateTapMX could help {company} achieve its goals. If you're interested in learning more, just reply to this email.

If not, no worries - I wish you and {company} all the best.

Best regards,
Sales Team
RateTapMX"""
            }
        ]

        for seq_data in sequences:
            sequence = Sequence(**seq_data)
            db.session.add(sequence)

        db.session.commit()
        print(f"✓ Added {len(sequences)} sequence steps")

        # Add leads to campaign
        for lead in leads:
            campaign_lead = CampaignLead(
                campaign_id=campaign.id,
                lead_id=lead.id,
                status='active'
            )
            db.session.add(campaign_lead)

        db.session.commit()
        print(f"✓ Added leads to campaign")

        print("\n" + "="*60)
        print("Sample data added successfully!")
        print("="*60)
        print("\nNext steps:")
        print("1. Update inbox credentials in the web interface")
        print("2. Test inbox connection")
        print("3. Activate campaign when ready")
        print("4. Start the application: python app.py")
        print("\nDefault login credentials:")
        print("  Username: admin")
        print("  Password: changeme")
        print("  (Change these in .env file)")


def main():
    parser = argparse.ArgumentParser(description='Initialize CRM database')
    parser.add_argument('--sample', action='store_true', help='Add sample data')
    args = parser.parse_args()

    # Initialize database
    init_database()

    # Add sample data if requested
    if args.sample:
        add_sample_data()
    else:
        print("\nDatabase initialized. Run with --sample flag to add sample data:")
        print("  python init_db.py --sample")


if __name__ == '__main__':
    main()
