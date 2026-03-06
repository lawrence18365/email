import os
import tempfile
import unittest
from datetime import datetime, timedelta


DB_FILE = os.path.join(tempfile.gettempdir(), "email_bounce_handler_test.db")
os.environ["DATABASE_URI"] = f"sqlite:///{DB_FILE}"

from app import app  # noqa: E402
from bounce_handler import BounceCleaner, BounceProcessor, BounceRecord, BounceType  # noqa: E402
from models import Campaign, CampaignLead, Inbox, Lead, db  # noqa: E402


class BounceHandlerSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        with app.app_context():
            db.session.query(CampaignLead).delete()
            db.session.query(Campaign).delete()
            db.session.query(Inbox).delete()
            db.session.query(Lead).delete()
            db.session.commit()

    def test_update_lead_status_accepts_scoped_session(self):
        with app.app_context():
            inbox = Inbox(
                name="Sender",
                email="sender@example.com",
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_use_tls=True,
                imap_host="imap.example.com",
                imap_port=993,
                imap_use_ssl=True,
                username="sender@example.com",
                password="secret",
                active=True,
                max_per_hour=5,
            )
            db.session.add(inbox)
            db.session.commit()

            campaign = Campaign(name="Bounce Test", inbox_id=inbox.id, status="active")
            lead = Lead(email="bounce@example.com", status="contacted")
            db.session.add_all([campaign, lead])
            db.session.commit()

            db.session.add(CampaignLead(campaign_id=campaign.id, lead_id=lead.id, status="active"))
            db.session.commit()

            processor = BounceProcessor(db.session)
            bounce = BounceRecord(
                email=lead.email,
                bounce_type=BounceType.HARD,
                reason="Hard bounce: user unknown",
                detected_at=datetime.utcnow(),
            )

            self.assertTrue(processor.update_lead_status(bounce))

            updated_lead = Lead.query.filter_by(email=lead.email).first()
            updated_campaign_lead = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                lead_id=lead.id,
            ).first()

            self.assertEqual(updated_lead.status, "bounced")
            self.assertIn("Hard bounce", updated_lead.email_verification_status)
            self.assertEqual(updated_campaign_lead.status, "stopped")

    def test_delete_hard_bounces_accepts_scoped_session(self):
        with app.app_context():
            old_bounce = Lead(
                email="old-bounce@example.com",
                status="bounced",
                updated_at=datetime.utcnow() - timedelta(days=45),
            )
            db.session.add(old_bounce)
            db.session.commit()

            cleaner = BounceCleaner(db.session)
            deleted = cleaner.delete_hard_bounces(min_age_days=30, dry_run=False)

            self.assertEqual(deleted, 1)
            self.assertIsNone(Lead.query.filter_by(email=old_bounce.email).first())


if __name__ == "__main__":
    unittest.main()
