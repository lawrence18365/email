from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Text, Integer, String, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship

db = SQLAlchemy()


class Lead(db.Model):
    """Lead/Contact model"""
    __tablename__ = 'leads'

    id = db.Column(Integer, primary_key=True)
    email = db.Column(String(255), unique=True, nullable=False, index=True)
    first_name = db.Column(String(100))
    last_name = db.Column(String(100))
    company = db.Column(String(255))
    website = db.Column(String(255))
    phone = db.Column(String(50))
    title = db.Column(String(100))  # Job title
    status = db.Column(String(50), default='new', index=True)  # new, contacted, responded, meeting_booked, not_interested
    source = db.Column(String(100))  # manual, csv_import, api, etc.
    created_at = db.Column(DateTime, default=datetime.utcnow)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Email verification
    email_verified = db.Column(Boolean, default=False)
    email_verification_status = db.Column(String(50))  # Deliverable, Undeliverable, Risky, Unknown
    email_verified_at = db.Column(DateTime)

    # Per-lead deadline (set when Email 1 is sent, used by AI responder)
    personal_deadline = db.Column(String(50))

    # Enrichment fields
    enriched = db.Column(Boolean, default=False)
    enriched_at = db.Column(DateTime)
    industry = db.Column(String(100))
    company_size = db.Column(String(50))  # 1-10, 11-50, 51-200, 201-500, 500+
    company_description = db.Column(Text)
    linkedin_url = db.Column(String(255))
    recent_news = db.Column(Text)  # JSON or text summary of recent news
    pain_points = db.Column(Text)  # Industry-specific pain points
    personalized_opener = db.Column(Text)  # AI-generated personalized opening line
    enrichment_data = db.Column(Text)  # Full JSON enrichment data for reference

    # Relationships
    sent_emails = relationship('SentEmail', back_populates='lead', cascade='all, delete-orphan')
    responses = relationship('Response', back_populates='lead', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Lead {self.email}>'

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or self.email


class Inbox(db.Model):
    """Email inbox configuration"""
    __tablename__ = 'inboxes'

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(100), nullable=False)
    email = db.Column(String(255), nullable=False, unique=True)

    # SMTP Configuration
    smtp_host = db.Column(String(255), nullable=False)
    smtp_port = db.Column(Integer, default=587)
    smtp_use_tls = db.Column(Boolean, default=True)

    # IMAP Configuration
    imap_host = db.Column(String(255), nullable=False)
    imap_port = db.Column(Integer, default=993)
    imap_use_ssl = db.Column(Boolean, default=True)

    # Credentials
    username = db.Column(String(255), nullable=False)
    password = db.Column(String(255), nullable=False)

    # Settings
    active = db.Column(Boolean, default=True)
    max_per_hour = db.Column(Integer, default=5)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    # Relationships
    campaigns = relationship('Campaign', back_populates='inbox')
    sent_emails = relationship('SentEmail', back_populates='inbox')

    def __repr__(self):
        return f'<Inbox {self.email}>'


class Campaign(db.Model):
    """Email campaign"""
    __tablename__ = 'campaigns'

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(255), nullable=False)
    inbox_id = db.Column(Integer, ForeignKey('inboxes.id'), nullable=False)
    status = db.Column(String(50), default='draft')  # draft, active, paused, completed
    created_at = db.Column(DateTime, default=datetime.utcnow)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    inbox = relationship('Inbox', back_populates='campaigns')
    sequences = relationship('Sequence', back_populates='campaign', cascade='all, delete-orphan', order_by='Sequence.step_number')
    sent_emails = relationship('SentEmail', back_populates='campaign')
    campaign_leads = relationship('CampaignLead', back_populates='campaign', cascade='all, delete-orphan')
    rotation_inboxes = relationship('CampaignInbox', back_populates='campaign', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Campaign {self.name}>'


class CampaignInbox(db.Model):
    """Rotation pool for campaigns (optional)"""
    __tablename__ = 'campaign_inboxes'

    id = db.Column(Integer, primary_key=True)
    campaign_id = db.Column(Integer, ForeignKey('campaigns.id'), nullable=False, index=True)
    inbox_id = db.Column(Integer, ForeignKey('inboxes.id'), nullable=False, index=True)
    added_at = db.Column(DateTime, default=datetime.utcnow)

    campaign = relationship('Campaign', back_populates='rotation_inboxes')
    inbox = relationship('Inbox')

    def __repr__(self):
        return f'<CampaignInbox campaign={self.campaign_id} inbox={self.inbox_id}>'


class Sequence(db.Model):
    """Email sequence step within a campaign"""
    __tablename__ = 'sequences'

    id = db.Column(Integer, primary_key=True)
    campaign_id = db.Column(Integer, ForeignKey('campaigns.id'), nullable=False)
    step_number = db.Column(Integer, nullable=False)  # 1, 2, 3, etc.
    delay_days = db.Column(Integer, default=0)  # Days after previous step (0 for first step)
    subject_template = db.Column(String(500), nullable=False)
    email_template = db.Column(Text, nullable=False)
    active = db.Column(Boolean, default=True)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    # Relationships
    campaign = relationship('Campaign', back_populates='sequences')
    sent_emails = relationship('SentEmail', back_populates='sequence')

    def __repr__(self):
        return f'<Sequence {self.campaign_id}-{self.step_number}>'


class CampaignLead(db.Model):
    """Junction table tracking which leads are in which campaigns"""
    __tablename__ = 'campaign_leads'

    id = db.Column(Integer, primary_key=True)
    campaign_id = db.Column(Integer, ForeignKey('campaigns.id'), nullable=False)
    lead_id = db.Column(Integer, ForeignKey('leads.id'), nullable=False)
    added_at = db.Column(DateTime, default=datetime.utcnow)
    status = db.Column(String(50), default='active')  # active, completed, stopped

    # Relationships
    campaign = relationship('Campaign', back_populates='campaign_leads')
    lead = relationship('Lead')

    def __repr__(self):
        return f'<CampaignLead campaign={self.campaign_id} lead={self.lead_id}>'


class SentEmail(db.Model):
    """Record of sent emails"""
    __tablename__ = 'sent_emails'

    id = db.Column(Integer, primary_key=True)
    lead_id = db.Column(Integer, ForeignKey('leads.id'), nullable=False)
    campaign_id = db.Column(Integer, ForeignKey('campaigns.id'), nullable=False)
    sequence_id = db.Column(Integer, ForeignKey('sequences.id'), nullable=False)
    inbox_id = db.Column(Integer, ForeignKey('inboxes.id'), nullable=False)

    sent_at = db.Column(DateTime, default=datetime.utcnow, index=True)
    message_id = db.Column(String(255), unique=True, index=True)  # For tracking replies
    subject = db.Column(String(500))
    body = db.Column(Text)
    status = db.Column(String(50), default='sent')  # sent, failed, bounced
    error_message = db.Column(Text)

    # Relationships
    lead = relationship('Lead', back_populates='sent_emails')
    campaign = relationship('Campaign', back_populates='sent_emails')
    sequence = relationship('Sequence', back_populates='sent_emails')
    inbox = relationship('Inbox', back_populates='sent_emails')
    responses = relationship('Response', back_populates='sent_email')

    def __repr__(self):
        return f'<SentEmail {self.message_id}>'


class Response(db.Model):
    """Received email responses"""
    __tablename__ = 'responses'

    id = db.Column(Integer, primary_key=True)
    lead_id = db.Column(Integer, ForeignKey('leads.id'), nullable=False)
    sent_email_id = db.Column(Integer, ForeignKey('sent_emails.id'))

    received_at = db.Column(DateTime, default=datetime.utcnow, index=True)
    message_id = db.Column(String(255), unique=True)
    in_reply_to = db.Column(String(255), index=True)  # Message-ID this is replying to
    subject = db.Column(String(500))
    body = db.Column(Text)

    # Manual status tracking
    reviewed = db.Column(Boolean, default=False)
    meeting_booked = db.Column(Boolean, default=False)
    notified = db.Column(Boolean, default=False)
    notes = db.Column(Text)
    assigned_to = db.Column(String(100))
    label = db.Column(String(50))

    # Relationships
    lead = relationship('Lead', back_populates='responses')
    sent_email = relationship('SentEmail', back_populates='responses')

    def __repr__(self):
        return f'<Response from {self.lead_id}>'


class SendingSchedule(db.Model):
    """Hourly sending limits per inbox"""
    __tablename__ = 'sending_schedule'

    id = db.Column(Integer, primary_key=True)
    inbox_id = db.Column(Integer, ForeignKey('inboxes.id'), nullable=False)
    hour_of_day = db.Column(Integer, nullable=False)  # 0-23
    max_per_hour = db.Column(Integer, default=5)
    active = db.Column(Boolean, default=True)

    inbox = relationship('Inbox')

    def __repr__(self):
        return f'<SendingSchedule inbox={self.inbox_id} hour={self.hour_of_day}>'
