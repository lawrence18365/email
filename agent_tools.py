"""
AI Agent Tools for CRM Operations

Provides helper functions for the AI agent to interact with the CRM database
and perform operations autonomously.
"""

from app import app, db
from models import Lead, Campaign, Sequence, Inbox, SentEmail, Response, CampaignLead
from email_handler import EmailSender, EmailReceiver, EmailPersonalizer
from datetime import datetime, timedelta
from sqlalchemy import func
import csv
from typing import List, Dict, Optional


class CRMAgent:
    """Helper class for AI agent to interact with CRM"""

    def __init__(self):
        self.app = app

    # ========================================================================
    # Lead Management
    # ========================================================================

    def add_lead(self, email: str, first_name: str = None, last_name: str = None,
                 company: str = None, website: str = None, source: str = "agent") -> dict:
        """Add a new lead to the CRM"""
        with self.app.app_context():
            # Check if exists
            existing = Lead.query.filter_by(email=email).first()
            if existing:
                return {"success": False, "message": f"Lead {email} already exists", "lead_id": existing.id}

            lead = Lead(
                email=email,
                first_name=first_name,
                last_name=last_name,
                company=company,
                website=website,
                source=source
            )
            db.session.add(lead)
            db.session.commit()

            return {"success": True, "message": f"Added lead {email}", "lead_id": lead.id}

    def import_leads_from_csv(self, csv_path: str) -> dict:
        """Import leads from CSV file"""
        with self.app.app_context():
            imported = 0
            skipped = 0
            errors = []

            try:
                with open(csv_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        email = row.get('email', '').strip()
                        if not email:
                            skipped += 1
                            continue

                        # Check if exists
                        if Lead.query.filter_by(email=email).first():
                            skipped += 1
                            continue

                        lead = Lead(
                            email=email,
                            first_name=row.get('first_name', '').strip(),
                            last_name=row.get('last_name', '').strip(),
                            company=row.get('company', '').strip(),
                            website=row.get('website', '').strip(),
                            source='csv_import_agent'
                        )
                        db.session.add(lead)
                        imported += 1

                db.session.commit()
                return {
                    "success": True,
                    "imported": imported,
                    "skipped": skipped,
                    "message": f"Imported {imported} leads, skipped {skipped}"
                }

            except Exception as e:
                return {"success": False, "message": f"Error importing CSV: {str(e)}"}

    def get_leads(self, status: str = None, limit: int = 100) -> List[dict]:
        """Get leads with optional filtering"""
        with self.app.app_context():
            query = Lead.query
            if status:
                query = query.filter_by(status=status)

            leads = query.limit(limit).all()

            return [{
                "id": lead.id,
                "email": lead.email,
                "name": lead.full_name,
                "company": lead.company,
                "status": lead.status,
                "created_at": lead.created_at.isoformat()
            } for lead in leads]

    def update_lead_status(self, lead_id: int, status: str) -> dict:
        """Update lead status"""
        with self.app.app_context():
            lead = Lead.query.get(lead_id)
            if not lead:
                return {"success": False, "message": "Lead not found"}

            lead.status = status
            db.session.commit()

            return {"success": True, "message": f"Updated lead status to {status}"}

    # ========================================================================
    # Campaign Management
    # ========================================================================

    def create_campaign(self, name: str, inbox_id: int, sequences: List[dict]) -> dict:
        """
        Create a campaign with sequences

        sequences format: [
            {"step": 1, "delay_days": 0, "subject": "...", "body": "..."},
            {"step": 2, "delay_days": 3, "subject": "...", "body": "..."}
        ]
        """
        with self.app.app_context():
            # Check inbox exists
            inbox = Inbox.query.get(inbox_id)
            if not inbox:
                return {"success": False, "message": "Inbox not found"}

            # Create campaign
            campaign = Campaign(
                name=name,
                inbox_id=inbox_id,
                status='draft'
            )
            db.session.add(campaign)
            db.session.commit()

            # Add sequences
            for seq_data in sequences:
                sequence = Sequence(
                    campaign_id=campaign.id,
                    step_number=seq_data['step'],
                    delay_days=seq_data.get('delay_days', 0),
                    subject_template=seq_data['subject'],
                    email_template=seq_data['body']
                )
                db.session.add(sequence)

            db.session.commit()

            return {
                "success": True,
                "campaign_id": campaign.id,
                "message": f"Created campaign '{name}' with {len(sequences)} steps"
            }

    def add_leads_to_campaign(self, campaign_id: int, lead_ids: List[int]) -> dict:
        """Add leads to a campaign"""
        with self.app.app_context():
            campaign = Campaign.query.get(campaign_id)
            if not campaign:
                return {"success": False, "message": "Campaign not found"}

            added = 0
            for lead_id in lead_ids:
                # Check if already in campaign
                existing = CampaignLead.query.filter_by(
                    campaign_id=campaign_id,
                    lead_id=lead_id
                ).first()

                if not existing:
                    campaign_lead = CampaignLead(
                        campaign_id=campaign_id,
                        lead_id=lead_id
                    )
                    db.session.add(campaign_lead)
                    added += 1

            db.session.commit()

            return {
                "success": True,
                "added": added,
                "message": f"Added {added} leads to campaign"
            }

    def activate_campaign(self, campaign_id: int) -> dict:
        """Activate a campaign"""
        with self.app.app_context():
            campaign = Campaign.query.get(campaign_id)
            if not campaign:
                return {"success": False, "message": "Campaign not found"}

            campaign.status = 'active'
            db.session.commit()

            return {"success": True, "message": f"Activated campaign '{campaign.name}'"}

    def pause_campaign(self, campaign_id: int) -> dict:
        """Pause a campaign"""
        with self.app.app_context():
            campaign = Campaign.query.get(campaign_id)
            if not campaign:
                return {"success": False, "message": "Campaign not found"}

            campaign.status = 'paused'
            db.session.commit()

            return {"success": True, "message": f"Paused campaign '{campaign.name}'"}

    def get_campaigns(self) -> List[dict]:
        """Get all campaigns with stats"""
        with self.app.app_context():
            campaigns = Campaign.query.all()

            results = []
            for campaign in campaigns:
                sent_count = SentEmail.query.filter_by(
                    campaign_id=campaign.id,
                    status='sent'
                ).count()

                response_count = db.session.query(Response).join(SentEmail).filter(
                    SentEmail.campaign_id == campaign.id
                ).count()

                lead_count = CampaignLead.query.filter_by(
                    campaign_id=campaign.id
                ).count()

                results.append({
                    "id": campaign.id,
                    "name": campaign.name,
                    "status": campaign.status,
                    "inbox": campaign.inbox.email,
                    "leads": lead_count,
                    "sent": sent_count,
                    "responses": response_count,
                    "response_rate": f"{(response_count/sent_count*100):.1f}%" if sent_count > 0 else "0%"
                })

            return results

    # ========================================================================
    # Response Analysis
    # ========================================================================

    def get_responses(self, status: str = None, limit: int = 50) -> List[dict]:
        """Get responses with optional filtering"""
        with self.app.app_context():
            query = Response.query

            if status == 'new':
                query = query.filter_by(reviewed=False)
            elif status == 'meeting_booked':
                query = query.filter_by(meeting_booked=True)

            responses = query.order_by(Response.received_at.desc()).limit(limit).all()

            return [{
                "id": resp.id,
                "lead": {
                    "id": resp.lead.id,
                    "email": resp.lead.email,
                    "name": resp.lead.full_name,
                    "company": resp.lead.company
                },
                "subject": resp.subject,
                "body": resp.body,
                "received_at": resp.received_at.isoformat(),
                "meeting_booked": resp.meeting_booked,
                "reviewed": resp.reviewed
            } for resp in responses]

    def mark_meeting_booked(self, response_id: int) -> dict:
        """Mark a response as meeting booked"""
        with self.app.app_context():
            response = Response.query.get(response_id)
            if not response:
                return {"success": False, "message": "Response not found"}

            response.meeting_booked = True
            response.reviewed = True
            response.lead.status = 'meeting_booked'

            db.session.commit()

            return {"success": True, "message": "Marked as meeting booked"}

    # ========================================================================
    # Analytics & Insights
    # ========================================================================

    def get_dashboard_stats(self) -> dict:
        """Get dashboard statistics"""
        with self.app.app_context():
            total_leads = Lead.query.count()
            active_campaigns = Campaign.query.filter_by(status='active').count()

            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            emails_sent_today = SentEmail.query.filter(
                SentEmail.sent_at >= today_start,
                SentEmail.status == 'sent'
            ).count()

            week_ago = datetime.utcnow() - timedelta(days=7)
            responses_this_week = Response.query.filter(
                Response.received_at >= week_ago
            ).count()

            meetings_booked = Response.query.filter_by(meeting_booked=True).count()

            # Lead status breakdown
            status_counts = dict(
                db.session.query(Lead.status, func.count(Lead.id))
                .group_by(Lead.status)
                .all()
            )

            return {
                "total_leads": total_leads,
                "active_campaigns": active_campaigns,
                "emails_sent_today": emails_sent_today,
                "responses_this_week": responses_this_week,
                "meetings_booked": meetings_booked,
                "lead_status": status_counts
            }

    def analyze_campaign_performance(self, campaign_id: int) -> dict:
        """Analyze campaign performance and provide insights"""
        with self.app.app_context():
            campaign = Campaign.query.get(campaign_id)
            if not campaign:
                return {"success": False, "message": "Campaign not found"}

            # Get metrics
            total_sent = SentEmail.query.filter_by(
                campaign_id=campaign_id,
                status='sent'
            ).count()

            responses = db.session.query(Response).join(SentEmail).filter(
                SentEmail.campaign_id == campaign_id
            ).count()

            meetings = db.session.query(Response).join(SentEmail).filter(
                SentEmail.campaign_id == campaign_id,
                Response.meeting_booked == True
            ).count()

            # Calculate rates
            response_rate = (responses / total_sent * 100) if total_sent > 0 else 0
            meeting_rate = (meetings / responses * 100) if responses > 0 else 0

            # Provide insights
            insights = []
            if response_rate < 5:
                insights.append("Low response rate - consider improving subject lines or personalization")
            elif response_rate > 15:
                insights.append("Excellent response rate - this campaign is performing well")

            if meeting_rate < 20 and responses > 0:
                insights.append("Many responses but few meetings - improve follow-up strategy")

            if total_sent == 0:
                insights.append("No emails sent yet - activate campaign to start")

            return {
                "success": True,
                "campaign": campaign.name,
                "metrics": {
                    "total_sent": total_sent,
                    "responses": responses,
                    "meetings": meetings,
                    "response_rate": f"{response_rate:.1f}%",
                    "meeting_rate": f"{meeting_rate:.1f}%"
                },
                "insights": insights
            }

    # ========================================================================
    # Inbox Management
    # ========================================================================

    def get_inboxes(self) -> List[dict]:
        """Get all configured inboxes"""
        with self.app.app_context():
            inboxes = Inbox.query.all()

            return [{
                "id": inbox.id,
                "name": inbox.name,
                "email": inbox.email,
                "active": inbox.active,
                "max_per_hour": inbox.max_per_hour
            } for inbox in inboxes]

    def test_inbox_connection(self, inbox_id: int) -> dict:
        """Test inbox SMTP and IMAP connections"""
        with self.app.app_context():
            inbox = Inbox.query.get(inbox_id)
            if not inbox:
                return {"success": False, "message": "Inbox not found"}

            sender = EmailSender(inbox)
            smtp_ok, smtp_msg = sender.test_connection()

            receiver = EmailReceiver(inbox)
            imap_ok, imap_msg = receiver.test_connection()

            return {
                "success": smtp_ok and imap_ok,
                "smtp": {"connected": smtp_ok, "message": smtp_msg},
                "imap": {"connected": imap_ok, "message": imap_msg}
            }

    # ========================================================================
    # AI Autopilot Features
    # ========================================================================

    def process_responses_and_reply(self) -> dict:
        """
        Process all pending responses and send AI-generated replies

        Full autopilot mode: AI reads, understands, and replies automatically
        """
        from ai_responder import AutoReplyScheduler

        with self.app.app_context():
            scheduler = AutoReplyScheduler(self.app, self.db.session)
            replies_sent = scheduler.process_pending_responses()

            return {
                "success": True,
                "replies_sent": replies_sent,
                "message": f"Processed responses and sent {replies_sent} AI-generated replies"
            }

    def find_new_leads(self, criteria: dict = None, limit: int = 20,
                       auto_add: bool = True) -> dict:
        """
        Find new leads automatically using AI prospecting

        Args:
            criteria: Optional dict with keys:
                - industry: "technology", "finance", etc.
                - location: "Mexico", "USA", etc.
                - company_size: "small", "medium", "large"
                - keywords: ["mortgage", "fintech"]
                - job_titles: ["CEO", "CFO"]
            limit: Maximum number of leads to find
            auto_add: Automatically add to database

        Returns:
            Dict with found, added, skipped counts and lead list
        """
        from lead_finder import LeadFinderScheduler

        with self.app.app_context():
            finder = LeadFinderScheduler(self.app, self.db)
            result = finder.run_prospecting(criteria, limit, auto_add)

            return {
                "success": True,
                "found": result['found'],
                "added": result['added'],
                "skipped": result['skipped'],
                "message": f"Found {result['found']} leads, added {result['added']} to database"
            }

    def enrich_lead(self, lead_id: int) -> dict:
        """Enrich a lead with additional information using AI (FREE)"""
        from lead_finder import FreeLeadFinder

        with self.app.app_context():
            lead = Lead.query.get(lead_id)
            if not lead:
                return {"success": False, "message": "Lead not found"}

            finder = FreeLeadFinder()
            enriched = finder.ai_enrich_lead({
                "email": lead.email,
                "company": lead.company,
                "website": lead.website
            })

            # Update lead with enriched data
            if enriched.get('first_name') and not lead.first_name:
                lead.first_name = enriched['first_name']
            if enriched.get('last_name') and not lead.last_name:
                lead.last_name = enriched['last_name']
            if enriched.get('company') and not lead.company:
                lead.company = enriched['company']

            self.db.session.commit()

            return {
                "success": True,
                "enriched_data": enriched,
                "message": f"Enriched lead {lead.email}"
            }

    def run_full_autopilot(self) -> dict:
        """
        Run complete autopilot cycle:
        1. Find new leads
        2. Add to active campaigns
        3. Process responses and send AI replies
        4. Optimize campaigns

        Returns comprehensive status report
        """
        results = {
            "prospecting": None,
            "campaign_assignment": None,
            "responses_processed": None,
            "optimization": None
        }

        with self.app.app_context():
            # 1. Find new leads
            try:
                from lead_finder import LeadFinderScheduler
                finder = LeadFinderScheduler(self.app, self.db)
                prospect_result = finder.run_prospecting(limit=10, auto_add=True)
                results["prospecting"] = {
                    "found": prospect_result['found'],
                    "added": prospect_result['added']
                }
            except Exception as e:
                results["prospecting"] = {"error": str(e)}

            # 2. Add new leads to best performing campaign
            try:
                new_leads = Lead.query.filter_by(status='new').limit(20).all()
                if new_leads:
                    # Find best campaign
                    best_campaign = self._find_best_campaign()
                    if best_campaign:
                        added = 0
                        for lead in new_leads:
                            existing = CampaignLead.query.filter_by(
                                campaign_id=best_campaign.id,
                                lead_id=lead.id
                            ).first()
                            if not existing:
                                cl = CampaignLead(
                                    campaign_id=best_campaign.id,
                                    lead_id=lead.id
                                )
                                self.db.session.add(cl)
                                added += 1
                        self.db.session.commit()
                        results["campaign_assignment"] = {
                            "campaign": best_campaign.name,
                            "leads_added": added
                        }
            except Exception as e:
                results["campaign_assignment"] = {"error": str(e)}

            # 3. Process responses and send AI replies
            try:
                from ai_responder import AutoReplyScheduler
                responder = AutoReplyScheduler(self.app, self.db.session)
                replies = responder.process_pending_responses()
                results["responses_processed"] = {"replies_sent": replies}
            except Exception as e:
                results["responses_processed"] = {"error": str(e)}

            # 4. Campaign optimization
            try:
                optimization = []
                campaigns = Campaign.query.filter_by(status='active').all()
                for campaign in campaigns:
                    perf = self._get_campaign_performance(campaign)
                    if perf['response_rate'] < 3 and perf['sent'] > 50:
                        campaign.status = 'paused'
                        optimization.append({
                            "campaign": campaign.name,
                            "action": "paused",
                            "reason": f"Low response rate ({perf['response_rate']:.1f}%)"
                        })
                self.db.session.commit()
                results["optimization"] = optimization if optimization else "No changes needed"
            except Exception as e:
                results["optimization"] = {"error": str(e)}

        return {
            "success": True,
            "results": results,
            "message": "Full autopilot cycle completed"
        }

    def _find_best_campaign(self):
        """Find the best performing active campaign"""
        best = None
        best_rate = 0

        campaigns = Campaign.query.filter_by(status='active').all()
        for campaign in campaigns:
            perf = self._get_campaign_performance(campaign)
            if perf['response_rate'] > best_rate:
                best_rate = perf['response_rate']
                best = campaign

        return best

    def _get_campaign_performance(self, campaign) -> dict:
        """Get performance metrics for a campaign"""
        sent = SentEmail.query.filter_by(
            campaign_id=campaign.id,
            status='sent'
        ).count()

        responses = self.db.session.query(Response).join(SentEmail).filter(
            SentEmail.campaign_id == campaign.id
        ).count()

        return {
            "sent": sent,
            "responses": responses,
            "response_rate": (responses / sent * 100) if sent > 0 else 0
        }
