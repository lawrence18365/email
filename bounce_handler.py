#!/usr/bin/env python3
"""
Bounce Handler - Automatic Email Bounce Detection & Management

Detects bounced emails via:
1. IMAP bounce folder monitoring
2. Response content analysis (AI-powered)
3. SMTP delivery failure tracking

Actions taken:
- Marks leads as 'bounced' 
- Stops campaigns for bounced leads
- Generates bounce reports
- Optionally deletes hard bounces after review period
"""

import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BounceType(Enum):
    HARD = "hard"           # Permanent failure (bad address, domain doesn't exist)
    SOFT = "soft"           # Temporary failure (mailbox full, server down)
    COMPLAINT = "complaint"  # Spam complaint
    UNKNOWN = "unknown"     # Can't determine type


@dataclass
class BounceRecord:
    """Represents a detected bounce"""
    email: str
    bounce_type: BounceType
    reason: str
    detected_at: datetime
    message_id: Optional[str] = None
    original_subject: Optional[str] = None
    raw_bounce_body: Optional[str] = None
    should_retry: bool = False


class BounceDetector:
    """Detects bounced emails from various sources"""
    
    # Common bounce indicators in email addresses/subjects
    BOUNCE_SENDERS = [
        'mailer-daemon',
        'mailerdaemon',
        'postmaster',
        'mail delivery subsystem',
        'mail delivery system',
        'bounce',
        'bounces',
        'noreply',
        'no-reply'
    ]
    
    # Hard bounce patterns (permanent failures)
    HARD_BOUNCE_PATTERNS = [
        r'user unknown',
        r'user not found',
        r'recipient address rejected',
        r'address does not exist',
        r'no such user',
        r'invalid address',
        r'domain not found',
        r'domain does not exist',
        r'account disabled',
        r'account suspended',
        r'account deleted',
        r'mailbox unavailable',
        r'recipient rejected',
        r'delivery failed.*permanent',
        r'permanent failure',
        r'550.*user',
        r'551.*user',
        r'552.*mailbox',
        r'5\.1\.1',  # SMTP 5.1.1 = Bad destination mailbox address
        r'5\.1\.2',  # SMTP 5.1.2 = Bad destination system address
        r'5\.1\.10', # SMTP 5.1.10 = Recipient address rejected
    ]
    
    # Soft bounce patterns (temporary failures)
    SOFT_BOUNCE_PATTERNS = [
        r'mailbox full',
        r'quota exceeded',
        r'mailbox quota',
        r'inbox full',
        r'temporary failure',
        r'try again later',
        r'deferred',
        r'greylisted',
        r'4\.2\.2',  # SMTP 4.2.2 = Mailbox full
        r'4\.3\.1',  # SMTP 4.3.1 = Mail system full
        r'4\.4\.1',  # SMTP 4.4.1 = No answer from host
        r'4\.4\.2',  # SMTP 4.4.2 = Bad connection
        r'4\.7\.1',  # SMTP 4.7.1 = Delivery not authorized
    ]
    
    # Spam complaint patterns
    COMPLAINT_PATTERNS = [
        r'complaint',
        r'feedback loop',
        r'fbl',
        r'abuse report',
        r'spam complaint',
        r'unsubscribe request',
        r'email marked as spam',
    ]
    
    def __init__(self, ai_enabled: bool = True):
        self.ai_enabled = ai_enabled
        self.hard_patterns = [re.compile(p, re.IGNORECASE) for p in self.HARD_BOUNCE_PATTERNS]
        self.soft_patterns = [re.compile(p, re.IGNORECASE) for p in self.SOFT_BOUNCE_PATTERNS]
        self.complaint_patterns = [re.compile(p, re.IGNORECASE) for p in self.COMPLAINT_PATTERNS]
    
    def is_bounce_email(self, from_email: str, subject: str = "") -> bool:
        """Check if an email is a bounce message based on sender/subject"""
        from_lower = from_email.lower()
        subject_lower = subject.lower()
        
        # Check sender
        for indicator in self.BOUNCE_SENDERS:
            if indicator in from_lower:
                return True
        
        # Check subject for common bounce indicators
        bounce_subjects = [
            'delivery status notification',
            'delivery failure',
            'undeliverable',
            'bounce',
            'mail delivery failed',
            'returned mail',
            'failed delivery'
        ]
        for indicator in bounce_subjects:
            if indicator in subject_lower:
                return True
        
        return False
    
    def detect_bounce_type(self, email_body: str, subject: str = "") -> Tuple[BounceType, str]:
        """Analyze bounce email content to determine bounce type and reason"""
        text = f"{subject}\n{email_body}".lower()
        
        # Check for complaints first (highest priority)
        for pattern in self.complaint_patterns:
            if pattern.search(text):
                return BounceType.COMPLAINT, "Spam complaint or abuse report"
        
        # Check for hard bounces
        for pattern in self.hard_patterns:
            match = pattern.search(text)
            if match:
                # Extract context around the match
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].strip()
                return BounceType.HARD, f"Hard bounce: {context}"
        
        # Check for soft bounces
        for pattern in self.soft_patterns:
            match = pattern.search(text)
            if match:
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].strip()
                return BounceType.SOFT, f"Soft bounce: {context}"
        
        # If we can't determine type, it's unknown
        return BounceType.UNKNOWN, "Unable to determine bounce type from content"
    
    def extract_bounced_email(self, email_body: str) -> Optional[str]:
        """Extract the original recipient email from bounce message"""
        # Common patterns for original recipient
        patterns = [
            r'original-recipient:\s*[^;]*;?\s*<?([^>\s]+@[^>\s]+)>?',
            r'final-recipient:\s*[^;]*;?\s*<?([^>\s]+@[^>\s]+)>?',
            r'diagnostic-code:[^\n]*\n[^\n]*<?([^>\s]+@[^>\s]+)>?',
            r'to:\s*<?([^>\s]+@[^>\s]+)>?',
            r'recipient:\s*<?([^>\s]+@[^>\s]+)>?',
            r'[<\s]([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})[>\s]',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, email_body, re.IGNORECASE)
            for match in matches:
                email = match.strip().lower()
                # Filter out common non-bounced addresses
                if email and not any(x in email for x in ['mailer-daemon', 'postmaster', 'noreply']):
                    return email
        
        return None


class BounceProcessor:
    """Processes detected bounces and updates database"""
    
    def __init__(self, db_session, detector: Optional[BounceDetector] = None):
        self.db = db_session
        self.detector = detector or BounceDetector()
    
    def process_bounce_folder(self, inbox) -> List[BounceRecord]:
        """Check bounce/quarantine folder for new bounces"""
        import imaplib
        import email
        from email.header import decode_header
        
        bounces_found = []
        
        try:
            mail = imaplib.IMAP4_SSL(inbox.imap_host, inbox.imap_port, timeout=30)
            mail.login(inbox.username, inbox.password)
            
            # Try common bounce/spam folders
            folders_to_check = ['Spam', 'Junk', 'Quarantine', 'Bounces', 'INBOX.Spam']
            
            for folder in folders_to_check:
                try:
                    status, _ = mail.select(folder)
                    if status != 'OK':
                        continue
                    
                    # Search for recent bounces (last 7 days)
                    since_date = (datetime.utcnow() - timedelta(days=7)).strftime('%d-%b-%Y')
                    status, messages = mail.search(None, f'SINCE {since_date}')
                    
                    if status != 'OK':
                        continue
                    
                    message_ids = messages[0].split()
                    
                    for msg_id in message_ids:
                        try:
                            status, msg_data = mail.fetch(msg_id, '(RFC822)')
                            if status != 'OK':
                                continue
                            
                            email_msg = email.message_from_bytes(msg_data[0][1])
                            
                            from_addr = email_msg.get('From', '')
                            subject = email_msg.get('Subject', '')
                            
                            # Check if this is a bounce
                            if not self.detector.is_bounce_email(from_addr, subject):
                                continue
                            
                            # Extract body
                            body = ""
                            if email_msg.is_multipart():
                                for part in email_msg.walk():
                                    content_type = part.get_content_type()
                                    if content_type == 'text/plain':
                                        try:
                                            body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                            break
                                        except:
                                            pass
                            else:
                                try:
                                    body = email_msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                                except:
                                    body = str(email_msg.get_payload())
                            
                            # Detect bounce type
                            bounce_type, reason = self.detector.detect_bounce_type(body, subject)
                            
                            # Extract bounced email address
                            bounced_email = self.detector.extract_bounced_email(body)
                            
                            if bounced_email:
                                bounce = BounceRecord(
                                    email=bounced_email,
                                    bounce_type=bounce_type,
                                    reason=reason,
                                    detected_at=datetime.utcnow(),
                                    message_id=email_msg.get('Message-ID', ''),
                                    original_subject=subject,
                                    raw_bounce_body=body[:1000]  # Truncate for storage
                                )
                                bounces_found.append(bounce)
                                
                        except Exception as e:
                            logger.warning(f"Error processing message {msg_id}: {e}")
                            continue
                    
                except Exception as e:
                    logger.debug(f"Could not check folder {folder}: {e}")
                    continue
            
            mail.logout()
            
        except Exception as e:
            logger.error(f"Error checking bounce folders: {e}")
        
        return bounces_found
    
    def process_smtp_failure(self, email: str, error_message: str) -> BounceRecord:
        """Process an SMTP delivery failure"""
        bounce_type, reason = self.detector.detect_bounce_type(error_message)
        
        return BounceRecord(
            email=email,
            bounce_type=bounce_type,
            reason=f"SMTP failure: {reason}",
            detected_at=datetime.utcnow(),
            should_retry=(bounce_type == BounceType.SOFT)
        )
    
    def update_lead_status(self, bounce: BounceRecord) -> bool:
        """Update lead status based on bounce"""
        from models import Lead, CampaignLead
        
        try:
            # Find lead by email
            lead = Lead.query.filter_by(email=bounce.email.lower()).first()
            
            if not lead:
                logger.warning(f"Bounced email not found in leads: {bounce.email}")
                return False
            
            # Update lead status
            if bounce.bounce_type == BounceType.HARD:
                lead.status = 'bounced'
                lead.notes = f"Hard bounce: {bounce.reason}"
                
                # Stop all campaigns for this lead
                campaign_leads = CampaignLead.query.filter_by(
                    lead_id=lead.id,
                    status='active'
                ).all()
                
                for cl in campaign_leads:
                    cl.status = 'stopped'
                    logger.info(f"Stopped campaign {cl.campaign_id} for bounced lead {bounce.email}")
                
                logger.info(f"Marked lead as bounced (hard): {bounce.email}")
                
            elif bounce.bounce_type == BounceType.COMPLAINT:
                lead.status = 'complained'
                lead.notes = f"Spam complaint: {bounce.reason}"
                
                # Also stop campaigns
                campaign_leads = CampaignLead.query.filter_by(
                    lead_id=lead.id,
                    status='active'
                ).all()
                
                for cl in campaign_leads:
                    cl.status = 'stopped'
                
                logger.info(f"Marked lead as complained: {bounce.email}")
                
            elif bounce.bounce_type == BounceType.SOFT:
                # Don't change status yet, but track the bounce
                lead.notes = f"Soft bounce ({datetime.utcnow().strftime('%Y-%m-%d')}): {bounce.reason}"
                logger.info(f"Recorded soft bounce for: {bounce.email}")
            
            self.db.session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error updating lead status for bounce: {e}")
            self.db.session.rollback()
            return False
    
    def generate_bounce_report(self, days: int = 30) -> Dict:
        """Generate a bounce report for the last N days"""
        from models import Lead
        
        since_date = datetime.utcnow() - timedelta(days=days)
        
        # Get bounced leads
        bounced = Lead.query.filter(
            Lead.status.in_(['bounced', 'complained']),
            Lead.updated_at >= since_date
        ).all()
        
        hard_bounces = [b for b in bounced if b.status == 'bounced']
        complaints = [b for b in bounced if b.status == 'complained']
        
        # Calculate bounce rate
        total_sent = Lead.query.filter(
            Lead.status.in_(['contacted', 'responded', 'bounced', 'complained']),
            Lead.updated_at >= since_date
        ).count()
        
        bounce_rate = (len(bounced) / total_sent * 100) if total_sent > 0 else 0
        
        report = {
            'period_days': days,
            'total_bounced': len(bounced),
            'hard_bounces': len(hard_bounces),
            'complaints': len(complaints),
            'bounce_rate_percent': round(bounce_rate, 2),
            'bounced_emails': [
                {
                    'email': b.email,
                    'status': b.status,
                    'reason': b.notes,
                    'date': b.updated_at.isoformat() if b.updated_at else None
                }
                for b in bounced[:50]  # Limit to 50 most recent
            ],
            'recommendations': []
        }
        
        # Add recommendations
        if bounce_rate > 5:
            report['recommendations'].append("High bounce rate detected (>5%). Review email list quality.")
        if len(complaints) > 0:
            report['recommendations'].append(f"{len(complaints)} spam complaints received. Review email content and sending practices.")
        if len(hard_bounces) > 10:
            report['recommendations'].append(f"{len(hard_bounces)} hard bounces. Consider cleaning your email list.")
        
        return report


class BounceCleaner:
    """Handles cleaning/removing bounced emails after review period"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def get_bounced_for_review(self, min_age_days: int = 30) -> List:
        """Get bounced leads that are ready for review/deletion"""
        from models import Lead
        
        cutoff_date = datetime.utcnow() - timedelta(days=min_age_days)
        
        return Lead.query.filter(
            Lead.status.in_(['bounced', 'complained']),
            Lead.updated_at <= cutoff_date
        ).all()
    
    def export_bounced(self, filepath: str):
        """Export bounced emails to CSV for review"""
        from models import Lead
        import csv
        
        bounced = Lead.query.filter(
            Lead.status.in_(['bounced', 'complained'])
        ).all()
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Email', 'Status', 'Reason', 'First Name', 'Last Name', 'Bounced Date'])
            
            for lead in bounced:
                writer.writerow([
                    lead.email,
                    lead.status,
                    lead.notes or '',
                    lead.first_name or '',
                    lead.last_name or '',
                    lead.updated_at.isoformat() if lead.updated_at else ''
                ])
        
        logger.info(f"Exported {len(bounced)} bounced emails to {filepath}")
        return len(bounced)
    
    def delete_hard_bounces(self, min_age_days: int = 30, dry_run: bool = True) -> int:
        """Permanently delete hard bounced leads after review period"""
        from models import Lead
        
        cutoff_date = datetime.utcnow() - timedelta(days=min_age_days)
        
        to_delete = Lead.query.filter(
            Lead.status == 'bounced',
            Lead.updated_at <= cutoff_date
        ).all()
        
        if dry_run:
            logger.info(f"[DRY RUN] Would delete {len(to_delete)} hard bounced leads")
            return len(to_delete)
        
        count = 0
        for lead in to_delete:
            self.db.session.delete(lead)
            count += 1
        
        self.db.session.commit()
        logger.info(f"Deleted {count} hard bounced leads")
        return count


# Convenience function for running bounce check
def check_and_process_bounces(app, db):
    """Main entry point: Check all inboxes for bounces and process them"""
    from models import Inbox
    
    processor = BounceProcessor(db.session)
    
    with app.app_context():
        inboxes = Inbox.query.filter_by(active=True).all()
        
        total_bounces = []
        
        for inbox in inboxes:
            logger.info(f"Checking bounces for {inbox.email}...")
            bounces = processor.process_bounce_folder(inbox)
            
            for bounce in bounces:
                processor.update_lead_status(bounce)
                total_bounces.append(bounce)
            
            logger.info(f"Found {len(bounces)} bounces in {inbox.email}")
        
        # Generate report
        report = processor.generate_bounce_report(days=30)
        
        return {
            'bounces_found': len(total_bounces),
            'report': report
        }


if __name__ == '__main__':
    # Test the detector
    detector = BounceDetector()
    
    # Test detection
    test_body = """
    Delivery Status Notification (Failure)
    
    The recipient's email address was not found.
    
    Final-Recipient: rfc822; nonexistent@example.com
    Action: failed
    Status: 5.1.1
    Diagnostic-Code: smtp; 550 5.1.1 User unknown
    """
    
    print("Testing bounce detection...")
    print(f"Is bounce: {detector.is_bounce_email('mailer-daemon@googlemail.com')}")
    
    bounce_type, reason = detector.detect_bounce_type(test_body)
    print(f"Bounce type: {bounce_type.value}")
    print(f"Reason: {reason}")
    
    bounced_email = detector.extract_bounced_email(test_body)
    print(f"Bounced email: {bounced_email}")
