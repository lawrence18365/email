import os
import sys
from app import app
from models import db, Lead, Inbox, SentEmail
from email_handler import EmailSender

def recover_deborah():
    print("Starting recovery for Deborah Perry...")
    with app.app_context():
        # 1. Find Deborah
        email = "dkperrymsw@gmail.com"
        lead = Lead.query.filter_by(email=email).first()
        if not lead:
            print(f"Error: Lead {email} not found!")
            return

        print(f"Found Deborah (ID: {lead.id}). Current status: {lead.status}")

        # 2. Resubscribe her
        if lead.status in ['not_interested', 'unsubscribed']:
            print(f"Resubscribing lead from {lead.status} to active...")
            lead.status = 'active'
            db.session.commit()
            print(f"✅ Updated status to: {lead.status}")
        else:
            print(f"Status is already {lead.status}. Ensuring it is active.")
            if lead.status != 'active':
                lead.status = 'active'
                db.session.commit()
                print(f"✅ Updated status to: {lead.status}")

        # 3. Send Recovery Email
        # Find the correct inbox
        inbox = Inbox.query.filter(Inbox.email.ilike("%weddingcounselors.com%")).first()
        if not inbox:
            inbox = Inbox.query.first() # Fallback
            if inbox:
                print(f"Warning: correct inbox not found, using {inbox.email}")
            else:
                print("Error: No inbox found!")
                return

        sender = EmailSender(inbox)
        subject = "Re: Your first week on Wedding Counselors"
        
        # Email body
        body = """Hi Deborah,

I owe you a real apology. Two things went wrong on our end, and I want to be completely transparent:

1. **The profile-saving issue was a bug on our side** — not anything you were doing wrong. When you saved your bio, our system showed a success message, but the data wasn't actually being written to the database. We found and fixed the bug this morning. Your profile will save correctly now.

2. **You should never have been unsubscribed.** Our automated system misread your email asking for help and incorrectly processed it as an unsubscribe request. That was a mistake, and I'm sorry for the frustration. You are fully re-subscribed and active.

Your founding member status is safe — nothing has changed with your account.

If you'd like, I'm happy to walk you through updating your profile over a quick call, or you can log in and try again at your dashboard: https://www.weddingcounselors.com/professional/dashboard

Either way, I'll personally make sure everything saves correctly.

Thank you for your patience, and again — I'm sorry for the trouble.

Sarah
Wedding Counselors Directory"""

        # Simple HTML conversion
        body_html = body.replace("\n", "<br>")
        
        # Add basic HTML wrapper if needed, but EmailSender might handle raw HTML or wrap it. 
        # Checking wrap_email_html in email_templates.py might be better but let's stick to simple provided content 
        # or use the wrapper if available.
        # Let's check if we can import wrap_email_html
        try:
            from email_templates import wrap_email_html
            print("Using email template wrapper...")
            final_html = wrap_email_html(body, inbox.email, lead=lead, include_unsubscribe=False)
        except ImportError:
            print("Warning: Could not import wrap_email_html, using basic HTML.")
            final_html = f"<html><body>{body_html}</body></html>"

        print("Sending recovery email...")
        bcc_email = os.getenv('NOTIFICATION_BCC_EMAIL')
        
        success, message_id, error = sender.send_email(
            to_email=lead.email,
            subject=subject,
            body_html=final_html,
            bcc=bcc_email
        )

        if success:
            print(f"✅ Email sent successfully! Message ID: {message_id}")
            # Log it
            sent_email = SentEmail(
                lead_id=lead.id,
                inbox_id=inbox.id,
                message_id=message_id,
                subject=subject,
                body=body,
                status='sent'
            )
            db.session.add(sent_email)
            db.session.commit()
            print("✅ Email logged to database.")
        else:
            print(f"❌ Failed to send email: {error}")

if __name__ == "__main__":
    recover_deborah()
