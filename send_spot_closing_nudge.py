#!/usr/bin/env python3
"""
SPOT-CLOSING NUDGE — Follow-up for warm leads who expressed interest but
haven't signed up yet. Urgency: founding member spots close March 15.

Run: python3 send_spot_closing_nudge.py --dry-run   (preview only)
     python3 send_spot_closing_nudge.py --send       (actually send)
"""
import os
import sys
import smtplib
import ssl
import json
import time
import sqlite3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid
from datetime import datetime
from types import SimpleNamespace

# Add CRM to path for wrap_email_html
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'crm'))
from email_templates import wrap_email_html, build_unsubscribe_url

# ─── Config ───
SMTP_HOST = "mail.spacemail.com"
SMTP_PORT = 465
EMAIL_FROM = "hello@weddingcounselors.com"
SIGNUP_LINK = "https://www.weddingcounselors.com/professional/signup"
TRACKER_FILE = os.path.join(os.path.dirname(__file__), "spot_closing_nudge_tracker.json")
CRM_DB = os.path.join(os.path.dirname(__file__), "crm", "instance", "crm.db")

def get_smtp_password():
    """Pull SMTP password from CRM database."""
    conn = sqlite3.connect(CRM_DB)
    cur = conn.cursor()
    cur.execute("SELECT password FROM inboxes WHERE email = ?", (EMAIL_FROM,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""

EMAIL_PASSWORD = get_smtp_password()

_LEAD_CACHE = {}


def get_lead_for_email(email_addr):
    """Return minimal lead object for unsubscribe token generation."""
    key = (email_addr or "").strip().lower()
    if not key:
        return None
    if key in _LEAD_CACHE:
        return _LEAD_CACHE[key]

    conn = sqlite3.connect(CRM_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email FROM leads WHERE lower(email) = ? LIMIT 1",
        (key,),
    )
    row = cur.fetchone()
    conn.close()

    lead = SimpleNamespace(id=row[0], email=row[1]) if row else None
    _LEAD_CACHE[key] = lead
    return lead

# ─── Nudge emails — personalized per lead ───
NUDGES = [
    # 1. Sobeyda Valle-Ellis — cold outreach Feb 20, no reply, 4 days
    {
        "to": "heartmattersnyc@gmail.com",
        "name": "Sobeyda",
        "subject": "Re: couple inquiry in New York — want in?",
        "body": f"""Hi Sobeyda,

Just following up on my note from last week. We have couples in New York actively looking for premarital counselors right now, and I'd love to get you listed before the founding member window closes.

Founding member listings are free permanently — no credit card, no fees. After March 15, new listings go to $29/month.

Here's the signup link (takes about 2 minutes): {SIGNUP_LINK}

If this isn't a fit, no worries at all.

Sarah
Wedding Counselors Directory"""
    },
    # 2. Stalin George — said "I would like to be on the register" Feb 18,
    #    we sent signup link Feb 19, no follow-through. 5 days.
    {
        "to": "goodnewscounseling.pella@gmail.com",
        "name": "Stalin",
        "subject": "Re: closing this out",
        "body": f"""Hi Stalin,

Just checking in — did you get a chance to sign up? I sent you the link last week but wanted to make sure it came through.

Here it is again: {SIGNUP_LINK}

Takes about 2 minutes. Just create your account, verify your email, and fill in the basics. You can add your full bio and photo later.

Founding member spots close March 15 — after that, new listings are $29/month. Your spot stays free permanently once you're in.

Sarah
Wedding Counselors Directory"""
    },
    # 3. Jamie Monday — asked about cost + dual-state (IN/IL), we answered,
    #    she said "Thank you!" Feb 17. Hasn't signed up. 6 days.
    {
        "to": "renew1025counseling@gmail.com",
        "name": "Jamie",
        "subject": "Re: founding member spot for Indiana counselors",
        "body": f"""Hi Jamie,

Just circling back — did you get a chance to set up your profile? To answer your earlier question, yes — you can absolutely be listed in both Indiana and Illinois. Just select your primary state during signup and we can add the second state to your profile.

Here's the link: {SIGNUP_LINK}

Takes about 2 minutes. Founding member spots close March 15, after which new listings are $29/month — but yours stays free permanently once you're in.

Sarah
Wedding Counselors Directory"""
    },
    # 4. Morgan Doutrich — interested since Feb 13, asked about pre-licensed
    #    status, we replied multiple times. Last contact Feb 17-18. 11 days.
    {
        "to": "morgandoutrichcounseling@gmail.com",
        "name": "Morgan",
        "subject": "Re: founding member spot for Tennessee counselors",
        "body": f"""Hi Morgan,

Quick follow-up — wanted to make sure you were able to get signed up. As I mentioned, you can select "Marriage and Family Therapist" and note your associate status in your bio. Your profile will still show up for couples searching in Tennessee.

Here's the link if you need it: {SIGNUP_LINK}

Founding member spots close March 15 — less than 3 weeks away. After that, new listings are $29/month.

Would hate for you to miss the free window after all our back and forth!

Sarah
Wedding Counselors Directory"""
    },
]


def record_sent_email_in_crm(lead_id, message_id, subject, body):
    """Record the nudge send in the CRM database so replies can be properly tracked."""
    try:
        conn = sqlite3.connect(CRM_DB)
        cur = conn.cursor()
        # Find the active campaign and its first sequence for FK references
        cur.execute("SELECT id FROM campaigns WHERE status = 'active' LIMIT 1")
        campaign_row = cur.fetchone()
        if not campaign_row:
            print("  WARNING: No active campaign found — send not recorded in CRM")
            conn.close()
            return
        campaign_id = campaign_row[0]

        cur.execute("SELECT id FROM sequences WHERE campaign_id = ? LIMIT 1", (campaign_id,))
        seq_row = cur.fetchone()
        if not seq_row:
            print("  WARNING: No sequence found — send not recorded in CRM")
            conn.close()
            return
        sequence_id = seq_row[0]

        cur.execute("SELECT id FROM inboxes WHERE email = ? LIMIT 1", (EMAIL_FROM,))
        inbox_row = cur.fetchone()
        if not inbox_row:
            print("  WARNING: No inbox found — send not recorded in CRM")
            conn.close()
            return
        inbox_id = inbox_row[0]

        cur.execute(
            """INSERT INTO sent_emails (lead_id, campaign_id, sequence_id, inbox_id, message_id, subject, body, status, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'sent', ?)""",
            (lead_id, campaign_id, sequence_id, inbox_id, message_id, subject, body, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
        print(f"  CRM: recorded SentEmail for lead {lead_id}")
    except Exception as e:
        print(f"  WARNING: Could not record in CRM: {e}")


def send_email(to, subject, body, lead=None, dry_run=True):
    """Send a single email via SMTP SSL."""
    if dry_run:
        print(f"\n{'='*60}")
        print(f"TO:      {to}")
        print(f"SUBJECT: {subject}")
        print(f"{'─'*60}")
        print(body)
        print(f"{'='*60}")
        return True

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Sarah <{EMAIL_FROM}>"
    msg["To"] = to
    msg["Subject"] = subject
    message_id = make_msgid(domain="weddingcounselors.com")
    msg["Message-ID"] = message_id

    unsubscribe_url = build_unsubscribe_url(lead) if lead else None
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>, <mailto:{EMAIL_FROM}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    else:
        msg["List-Unsubscribe"] = f"<mailto:{EMAIL_FROM}?subject=unsubscribe>"

    # Plain text
    msg.attach(MIMEText(body, "plain"))
    # HTML version
    html_body = wrap_email_html(body, EMAIL_FROM, lead=lead, include_unsubscribe=True)
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"  SENT to {to}")
        # Record in CRM so reply detection works properly
        if lead:
            record_sent_email_in_crm(lead.id, message_id, subject, body)
        return True
    except Exception as e:
        print(f"  FAILED to {to}: {e}")
        return False


def load_tracker():
    """Load send tracker from disk."""
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE) as f:
            return json.load(f)
    return {"sends": []}


def save_tracker(tracker):
    """Save send tracker to disk."""
    with open(TRACKER_FILE, "w") as f:
        json.dump(tracker, f, indent=2)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Actually send (default is dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=8.0,
        help="Delay between live sends to reduce burstiness",
    )
    args = parser.parse_args()

    dry_run = not args.send

    print(f"\n{'🔵 DRY RUN — preview only' if dry_run else '🟢 SENDING FOR REAL'}")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Spot-closing nudge emails: {len(NUDGES)}")
    print(f"Deadline: March 15, 2026")

    if not dry_run and not EMAIL_PASSWORD:
        print("\n✗ ERROR: Could not load SMTP password from CRM database")
        sys.exit(1)

    tracker = load_tracker()
    sent = 0
    failed = 0

    for index, nudge in enumerate(NUDGES, start=1):
        lead = get_lead_for_email(nudge["to"])
        ok = send_email(
            nudge["to"],
            nudge["subject"],
            nudge["body"],
            lead=lead,
            dry_run=dry_run,
        )
        if ok:
            sent += 1
            if not dry_run:
                tracker["sends"].append({
                    "to": nudge["to"],
                    "name": nudge["name"],
                    "subject": nudge["subject"],
                    "sent_at": datetime.now().isoformat(),
                    "campaign": "spot_closing_nudge",
                })
        else:
            failed += 1

        if not dry_run and args.delay_seconds > 0 and index < len(NUDGES):
            time.sleep(args.delay_seconds)

    if not dry_run:
        save_tracker(tracker)
        print(f"\n  Tracker saved to {TRACKER_FILE}")

    print(f"\n{'─'*40}")
    print(f"Total: {sent} sent, {failed} failed")
    if dry_run:
        print(f"\nTo send for real: python3 send_spot_closing_nudge.py --send")


if __name__ == "__main__":
    main()
