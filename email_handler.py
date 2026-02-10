import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formataddr
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiting for email sending per inbox"""

    def __init__(self, db_session):
        self.db = db_session

    def can_send(self, inbox_id: int, max_per_hour: int) -> bool:
        """Check if we can send from this inbox within rate limit"""
        from models import SentEmail

        one_hour_ago = datetime.utcnow() - timedelta(hours=1)

        sent_count = self.db.query(SentEmail).filter(
            SentEmail.inbox_id == inbox_id,
            SentEmail.sent_at >= one_hour_ago,
            SentEmail.status == 'sent'
        ).count()

        return sent_count < max_per_hour

    def get_available_inbox(self, inbox_ids: List[int], max_per_hour: int) -> Optional[int]:
        """Get the first available inbox that can send (round-robin)"""
        for inbox_id in inbox_ids:
            if self.can_send(inbox_id, max_per_hour):
                return inbox_id
        return None

    def get_hourly_count(self, inbox_id: int) -> int:
        """Get number of emails sent in the last hour"""
        from models import SentEmail

        one_hour_ago = datetime.utcnow() - timedelta(hours=1)

        return self.db.query(SentEmail).filter(
            SentEmail.inbox_id == inbox_id,
            SentEmail.sent_at >= one_hour_ago,
            SentEmail.status == 'sent'
        ).count()


class EmailSender:
    """Handle SMTP email sending"""

    def __init__(self, inbox):
        """
        Initialize with an Inbox model instance
        """
        self.inbox = inbox
        self.smtp_host = inbox.smtp_host
        self.smtp_port = inbox.smtp_port
        self.smtp_use_tls = inbox.smtp_use_tls
        self.imap_host = inbox.imap_host
        self.imap_port = inbox.imap_port
        self.username = inbox.username
        self.password = inbox.password
        self.from_email = inbox.email
        self.from_name = inbox.name

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_plain: Optional[str] = None,
        bcc: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Send an email via SMTP

        Returns: (success: bool, message_id: str, error_message: str)
        """
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = formataddr((self.from_name, self.from_email))
            msg['To'] = to_email
            msg['Subject'] = subject
            msg['Date'] = email.utils.formatdate(localtime=True)

            # Generate unique Message-ID
            message_id = make_msgid(domain=self.from_email.split('@')[1])
            msg['Message-ID'] = message_id

            # Threading headers for reply-in-thread
            if in_reply_to:
                msg['In-Reply-To'] = in_reply_to
            if references:
                msg['References'] = references

            # Add plain text version (if not provided, strip HTML)
            if body_plain is None:
                body_plain = self._html_to_plain(body_html)

            msg.attach(MIMEText(body_plain, 'plain'))
            msg.attach(MIMEText(body_html, 'html'))

            # Build recipient list (to + bcc)
            recipients = [to_email]
            if bcc:
                recipients.append(bcc)

            # Connect and send
            if self.smtp_use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)

            server.login(self.username, self.password)
            server.sendmail(self.from_email, recipients, msg.as_string())
            server.quit()

            # Save copy to Sent folder via IMAP
            try:
                self._save_to_sent_folder(msg)
            except Exception as e:
                logger.warning(f"Could not save to Sent folder: {e}")

            logger.info(f"Email sent successfully to {to_email} with Message-ID: {message_id}")
            return True, message_id, None

        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"SMTP Authentication failed: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

        except smtplib.SMTPException as e:
            error_msg = f"SMTP error: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

    def _save_to_sent_folder(self, msg):
        """Save a copy of the sent email to IMAP Sent folder"""
        import imaplib
        import time

        try:
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=30)
            mail.login(self.username, self.password)

            # Try common sent folder names
            sent_folders = ['Sent', '[Gmail]/Sent Mail', 'INBOX.Sent', 'Sent Items', 'Sent Mail']
            for folder in sent_folders:
                try:
                    status, _ = mail.select(folder)
                    if status == 'OK':
                        # Append message to Sent folder
                        mail.append(folder, '\\Seen', imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                        logger.info(f"Saved copy to Sent folder: {folder}")
                        mail.logout()
                        return True
                except:
                    continue

            mail.logout()
            logger.warning("Could not find Sent folder to save copy")
            return False

        except Exception as e:
            logger.warning(f"Failed to save to Sent folder: {e}")
            return False

    def _html_to_plain(self, html: str) -> str:
        """Convert HTML to plain text (basic)"""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        # Decode HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        return text.strip()

    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test SMTP connection and credentials"""
        try:
            if self.smtp_use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)

            server.login(self.username, self.password)
            server.quit()

            return True, "Connection successful"

        except Exception as e:
            return False, str(e)


class EmailReceiver:
    """Handle IMAP email receiving"""

    def __init__(self, inbox):
        """Initialize with an Inbox model instance"""
        self.inbox = inbox
        self.imap_host = inbox.imap_host
        self.imap_port = inbox.imap_port
        self.imap_use_ssl = inbox.imap_use_ssl
        self.username = inbox.username
        self.password = inbox.password

    def fetch_new_responses(self) -> List[Dict]:
        """
        Fetch recent emails from inbox (last 3 days).

        Uses SINCE date filter instead of UNSEEN so that emails read
        in another mail client are still picked up.  Duplicate prevention
        is handled by the caller via message_id checks in the DB.

        Returns list of dicts with keys: message_id, in_reply_to, subject, body, date
        """
        responses = []

        try:
            # Connect to IMAP
            if self.imap_use_ssl:
                mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=30)
            else:
                mail = imaplib.IMAP4(self.imap_host, self.imap_port, timeout=30)

            mail.login(self.username, self.password)
            mail.select('INBOX')

            # Search for messages from the last 3 days (catches read emails too)
            since_date = (datetime.utcnow() - timedelta(days=3)).strftime('%d-%b-%Y')
            status, messages = mail.search(None, f'SINCE {since_date}')

            if status != 'OK':
                logger.warning(f"No unread messages found in {self.inbox.email}")
                mail.logout()
                return responses

            message_ids = messages[0].split()

            for msg_id in message_ids:
                try:
                    # Fetch email
                    status, msg_data = mail.fetch(msg_id, '(RFC822)')

                    if status != 'OK':
                        continue

                    # Parse email
                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)

                    # Extract headers
                    message_id = email_message.get('Message-ID', '').strip('<>')
                    in_reply_to = email_message.get('In-Reply-To', '').strip('<>')
                    references = email_message.get('References', '')
                    subject = email_message.get('Subject', '')
                    from_addr = email_message.get('From', '')
                    date_str = email_message.get('Date', '')

                    # Parse date
                    date = datetime.utcnow()
                    if date_str:
                        try:
                            date = email.utils.parsedate_to_datetime(date_str)
                        except:
                            pass

                    # Extract body
                    body = self._get_email_body(email_message)

                    responses.append({
                        'message_id': message_id,
                        'in_reply_to': in_reply_to,
                        'references': references,
                        'subject': subject,
                        'from': from_addr,
                        'body': body,
                        'date': date
                    })

                except Exception as e:
                    logger.error(f"Error processing message {msg_id}: {str(e)}")
                    continue

            mail.logout()
            logger.info(f"Fetched {len(responses)} new responses from {self.inbox.email}")

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error for {self.inbox.email}: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error fetching emails from {self.inbox.email}: {str(e)}")

        return responses

    def _get_email_body(self, email_message) -> str:
        """Extract email body (prefer plain text, fallback to HTML)"""
        body = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))

                # Skip attachments
                if 'attachment' in content_disposition:
                    continue

                if content_type == 'text/plain':
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    except:
                        pass

                elif content_type == 'text/html' and not body:
                    try:
                        html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        body = self._html_to_plain(html_body)
                    except:
                        pass
        else:
            try:
                body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                body = str(email_message.get_payload())

        return body.strip()

    def _html_to_plain(self, html: str) -> str:
        """Convert HTML to plain text (basic)"""
        text = re.sub(r'<[^>]+>', '', html)
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        return text.strip()

    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test IMAP connection and credentials"""
        try:
            if self.imap_use_ssl:
                mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=10)
            else:
                mail = imaplib.IMAP4(self.imap_host, self.imap_port, timeout=10)

            mail.login(self.username, self.password)
            mail.select('INBOX')
            mail.logout()

            return True, "Connection successful"

        except Exception as e:
            return False, str(e)


class EmailPersonalizer:
    """Personalize email templates with lead data"""

    @staticmethod
    def personalize(template: str, lead) -> str:
        """
        Replace template variables with lead data

        Supported variables:
        - {firstName} or {first_name}
        - {lastName} or {last_name}
        - {fullName} or {full_name}
        - {email}
        - {company}
        - {website}
        - {personalizedOpener} or {opener} - AI-generated personalized opener
        - {industry}
        - {title} or {jobTitle}

        Fallback syntax: {variable|fallback} - uses fallback if variable is empty
        Example: {firstName|there} -> "Katie" if firstName exists, "there" if not
        """
        # Get personalized opener or use fallback
        opener = getattr(lead, 'personalized_opener', None) or ''
        if not opener and lead.company:
            opener = f"I came across {lead.company} and wanted to reach out."

        # Build values dict for lookups
        values = {
            'firstName': lead.first_name or '',
            'first_name': lead.first_name or '',
            'lastName': lead.last_name or '',
            'last_name': lead.last_name or '',
            'fullName': lead.full_name or '',
            'full_name': lead.full_name or '',
            'email': lead.email or '',
            'company': lead.company or '',
            'website': lead.website or '',
            'personalizedOpener': opener,
            'opener': opener,
            'industry': getattr(lead, 'industry', '') or '',
            'title': getattr(lead, 'title', '') or '',
            'jobTitle': getattr(lead, 'title', '') or '',
        }

        result = template

        # First handle fallback syntax: {variable|fallback}
        fallback_pattern = re.compile(r'\{(\w+)\|([^}]+)\}')
        def replace_with_fallback(match):
            var_name = match.group(1)
            fallback = match.group(2)
            value = values.get(var_name, '')
            return value if value else fallback

        result = fallback_pattern.sub(replace_with_fallback, result)

        # Then handle standard replacements
        for var_name, value in values.items():
            result = result.replace('{' + var_name + '}', value)

        return result
