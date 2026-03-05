#!/usr/bin/env python3
"""
NUDGE CAMPAIGN — Personal check-ins for warm leads who said yes but haven't signed up.
Each email is hand-crafted based on their conversation history.

Run: python send_nudge_campaign.py --dry-run   (preview only)
     python send_nudge_campaign.py --send       (actually send)
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
EMAIL_PASSWORD = os.environ.get("WEDDING_EMAIL_PASSWORD", "")
SIGNUP_LINK = "https://www.weddingcounselors.com/professional/signup?utm_source=email&utm_medium=nudge&utm_campaign=founding_member_checkin"
CRM_DB = os.path.join(os.path.dirname(__file__), "crm", "instance", "crm.db")
TRACKER_FILE = os.path.join(os.path.dirname(__file__), "nudge_campaign_tracker.json")

# ─── Nudge emails — personalized per lead ───
NUDGES = [
    # ──── TIER 1: Said YES clearly, 7-15 days ago, haven't come back ────
    {
        "to": "frankmacarthurpsyd@gmail.com",
        "name": "Dr. MacArthur",
        "subject": "Re: founding member spot for New Jersey counselors",
        "body": f"""Hi Dr. MacArthur,

Just checking in — did you get a chance to set up your profile? I know things get busy.

Here's the direct link if you still want your free founding member listing: {SIGNUP_LINK}

Takes about 2 minutes. Founding member spots close March 15, after which it's $29/month.

Happy to help if you hit any issues.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "boxelderbehavioralhealth@gmail.com",
        "name": "Martha",
        "subject": "Re: founding member spot for North Carolina counselors",
        "body": f"""Hi Martha,

Quick follow-up — wanted to make sure you were able to claim your free listing. A few counselors had trouble with the signup earlier, but we've fixed everything on our end.

If you haven't had a chance yet, here's the link: {SIGNUP_LINK}

Your founding member spot is locked in free forever once you sign up. After March 15, new listings go to $29/month.

Let me know if you need anything.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "anthonythomas.lcsw@gmail.com",
        "name": "Anthony",
        "subject": "Re: founding member spot for North Carolina counselors",
        "body": f"""Hi Anthony,

Just circling back — did you get a chance to set up your profile?

Here's the direct link: {SIGNUP_LINK}

It takes about 2 minutes — just your name, credentials, and location to go live. You can add your full bio and photo later.

Founding member spots close March 15. After that, new counselors pay $29/month.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "jadoradorlmft@gmail.com",
        "name": "Jeffrey",
        "subject": "Re: founding member spot for Rhode Island counselors",
        "body": f"""Hi Jeffrey,

Checking in — did you get a chance to claim your listing?

The signup is quick (2-3 minutes): {SIGNUP_LINK}

Just create your account, verify your email, and fill in the basics. Couples in Rhode Island are already searching the directory.

Founding member spots close March 15. After that it's $29/month — but yours stays free permanently once you're in.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "mindovermattermft@gmail.com",
        "name": "there",
        "subject": "Re: founding member spot for New York counselors",
        "body": f"""Hi there,

Just following up — no scheduling needed to get listed. You can sign up directly here:

{SIGNUP_LINK}

Takes about 2 minutes. Just create your account, verify email, and add your basics. You can always come back to add more detail later.

Founding member spots close March 15 — after that, listings are $29/month.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "birminghampremarital@gmail.com",
        "name": "John",
        "subject": "Re: founding member spot for Michigan counselors",
        "body": f"""Hi John,

Checking in — did you get a chance to set up your listing?

Here's the link: {SIGNUP_LINK}

Takes about 2 minutes. Couples in Michigan are already finding counselors through the directory.

Your founding member spot is free permanently — but the window closes March 15. After that, new listings are $29/month.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "pastorpaulgates@gmail.com",
        "name": "Pastor Gates",
        "subject": "Re: founding member spot for Hawaii counselors",
        "body": f"""Hi Pastor Gates,

Just following up — were you able to set up your profile? As I mentioned, ordained pastors are absolutely welcome. Several of our founding members are faith-based counselors.

Here's the signup link: {SIGNUP_LINK}

Your free listing is locked in permanently once you sign up. Founding member spots close March 15.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "forwardmomentumtherapy@gmail.com",
        "name": "there",
        "subject": "Re: founding member spot for Nebraska counselors",
        "body": f"""Hi there,

Following up on your question — just wanted to make sure you had everything you needed.

If you'd like to claim your free founding member listing, here's the link: {SIGNUP_LINK}

Quick recap: it's completely free (no fees, no credit card), takes 2 minutes, and you get a dedicated profile page where couples in Nebraska can find you directly.

The founding member window closes March 15 — after that, new listings are $29/month.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "abernarduccilcsw@gmail.com",
        "name": "Alicia",
        "subject": "Re: founding member spot for New Jersey counselors",
        "body": f"""Hi Alicia,

Just circling back — to confirm, you will never be charged for your founding member listing. It's free permanently, no credit card needed, no hidden fees.

If you'd like to get set up: {SIGNUP_LINK}

Takes about 2 minutes. Founding member spots close March 15, after which new listings are $29/month — but your spot stays free forever once you're in.

Sarah
Wedding Counselors Directory"""
    },
    # ──── TIER 2: Hit bugs previously, need "it's fixed now" nudge ────
    {
        "to": "drwilliamryan@gmail.com",
        "name": "Dr. Ryan",
        "subject": "Re: founding member spot for New York counselors",
        "body": f"""Hi Dr. Ryan,

Quick update — the error you ran into ("moderation_reviewed_at" column issue) has been fixed. The signup and profile editor are working smoothly now.

If you'd like to try again: {SIGNUP_LINK}

Your founding member listing is free permanently. The window closes March 15.

Let me know if you hit any issues — happy to help.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "dkperrymsw@gmail.com",
        "name": "Deborah",
        "subject": "Re: Your first week on Wedding Counselors",
        "body": f"""Hi Deborah,

I wanted to personally follow up — the "permission denied" error you experienced has been fixed. Your profile data should save correctly now.

If you'd like to try again, here's the link: {SIGNUP_LINK}

I know the experience was frustrating, and I'm sorry about that. We've made significant improvements to the platform since then.

Your founding member listing is free permanently — that offer closes March 15.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "maritalminister@gmail.com",
        "name": "Minister Brown",
        "subject": "Re: founding member spot for Virginia counselors",
        "body": f"""Hi Minister Brown,

Just checking in — were you able to sign up after the fixes? A few counselors had trouble earlier, but everything is running smoothly now.

Here's the link if you need it: {SIGNUP_LINK}

Your free founding member listing is locked in permanently once you sign up. The window closes March 15, after which new listings are $29/month.

Sarah
Wedding Counselors Directory"""
    },
    # ──── TIER 3: Said yes, already got many emails, lighter touch ────
    {
        "to": "annaholdingscompany@gmail.com",
        "name": "Anastasia",
        "subject": "Re: founding member spot for Louisiana counselors",
        "body": f"""Hi Anastasia,

Just a quick note — did you get a chance to claim your listing? The link is here if you need it: {SIGNUP_LINK}

Founding member spots close March 15.

Sarah
Wedding Counselors Directory"""
    },
    {
        "to": "enrichyourrelationship@gmail.com",
        "name": "Sarah",
        "subject": "Re: founding member spot for Minnesota counselors",
        "body": f"""Hi Sarah,

Following up — were you able to set up your profile? Here's the link if you need it: {SIGNUP_LINK}

Founding member spots close March 15. Takes about 2 minutes.

Sarah
Wedding Counselors Directory"""
    },
]

# ──── Skip list — leads who are likely already signed up or too recent ────
# Dr. Russo (17 exchanges, completed profile)
# Pamela (completed profile, said "finished doing it")
# Britney Halversen (said "filling out the form now")
# Jim Stites & Good News Counseling (said yes 2d ago, AI already replied)
# Maya Mason (asked "is it free" 2d ago, too recent)
# Morgan (2d ago, too recent)
# Jamie/Renew1025 (asked about dual state, AI replied)
# Dr. Svatovic (auto-reply)
# Jim Brazel (email change, already contacted at new address)


_LEAD_CACHE = {}


def get_lead_for_email(email_addr):
    """Return minimal lead object for unsubscribe token generation."""
    key = (email_addr or "").strip().lower()
    if not key:
        return None
    if key in _LEAD_CACHE:
        return _LEAD_CACHE[key]

    try:
        conn = sqlite3.connect(CRM_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email FROM leads WHERE lower(email) = ? LIMIT 1",
            (key,),
        )
        row = cur.fetchone()
        conn.close()
    except Exception:
        row = None

    lead = SimpleNamespace(id=row[0], email=row[1]) if row else None
    _LEAD_CACHE[key] = lead
    return lead


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
    # HTML version using CRM's professional template
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
    print(f"Nudge emails to send: {len(NUDGES)}")

    if not dry_run and not EMAIL_PASSWORD:
        print("\nERROR: Set WEDDING_EMAIL_PASSWORD environment variable")
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
                    "campaign": "nudge_campaign",
                })
        else:
            failed += 1

        if not dry_run and args.delay_seconds > 0 and index < len(NUDGES):
            time.sleep(args.delay_seconds)

    if not dry_run:
        save_tracker(tracker)
        print(f"\nTracker saved to {TRACKER_FILE}")

    print(f"\n{'─'*40}")
    print(f"Total: {sent} sent, {failed} failed")
    if dry_run:
        print(f"\nTo send for real: python send_nudge_campaign.py --send")


if __name__ == "__main__":
    main()
