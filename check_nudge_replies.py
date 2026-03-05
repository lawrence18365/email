#!/usr/bin/env python3
"""
Check for replies to the nudge campaign from the email inbox (IMAP)
and cross-reference with CRM audit database.
"""

import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import sqlite3
import sys

# ── Configuration ──────────────────────────────────────────────────────────

IMAP_HOST = "mail.spacemail.com"
IMAP_PORT = 993
CRM_DB = "/Users/lawrence/Desktop/email/crm/instance/crm.db"
AUDIT_DB = "/Users/lawrence/Desktop/email/crm/crm-audit.db"

NUDGE_RECIPIENTS = [
    "frankmacarthurpsyd@gmail.com",
    "boxelderbehavioralhealth@gmail.com",
    "anthonythomas.lcsw@gmail.com",
    "jadoradorlmft@gmail.com",
    "mindovermattermft@gmail.com",
    "birminghampremarital@gmail.com",
    "pastorpaulgates@gmail.com",
    "forwardmomentumtherapy@gmail.com",
    "abernarduccilcsw@gmail.com",
    "drwilliamryan@gmail.com",
    "dkperrymsw@gmail.com",
    "maritalminister@gmail.com",
    "annaholdingscompany@gmail.com",
    "enrichyourrelationship@gmail.com",
]

# ── Helpers ────────────────────────────────────────────────────────────────

def decode_mime_header(header_value):
    """Decode a MIME-encoded header into a plain string."""
    if header_value is None:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def get_email_body(msg):
    """Extract the plain-text body from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disp = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body += payload.decode(charset, errors="replace")
        # If no plain text found, try HTML
        if not body.strip():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body += "[HTML] " + payload.decode(charset, errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    return body.strip()


def extract_sender_email(from_header):
    """Extract just the email address from a From header."""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].lower().strip()
    return from_header.lower().strip()


# ── Get IMAP credentials from CRM DB ──────────────────────────────────────

print("=" * 80)
print("NUDGE CAMPAIGN REPLY CHECK")
print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

print("\n[1] Loading IMAP credentials from CRM database...")
conn = sqlite3.connect(CRM_DB)
cur = conn.cursor()
cur.execute(
    "SELECT username, password FROM inboxes WHERE email = 'hello@weddingcounselors.com'"
)
row = cur.fetchone()
conn.close()

if not row:
    print("ERROR: Could not find inbox credentials for hello@weddingcounselors.com")
    sys.exit(1)

imap_user, imap_pass = row
print(f"    Inbox: hello@weddingcounselors.com")
print(f"    IMAP:  {IMAP_HOST}:{IMAP_PORT} (SSL)")

# ── Connect to IMAP and search ────────────────────────────────────────────

print("\n[2] Connecting to IMAP server...")
try:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(imap_user, imap_pass)
    print("    Connected and authenticated successfully.")
except Exception as e:
    print(f"ERROR connecting to IMAP: {e}")
    sys.exit(1)

# Select INBOX
mail.select("INBOX")

# Search for emails from nudge recipients in the last 14 days
since_date = (datetime.now() - timedelta(days=14)).strftime("%d-%b-%Y")
print(f"\n[3] Searching for replies from nudge recipients since {since_date}...")

inbox_replies = []

for addr in NUDGE_RECIPIENTS:
    search_criteria = f'(FROM "{addr}" SINCE {since_date})'
    try:
        status, data = mail.search(None, search_criteria)
        if status != "OK":
            continue
        msg_ids = data[0].split()
        if not msg_ids:
            continue

        for msg_id in msg_ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            from_addr = extract_sender_email(decode_mime_header(msg.get("From", "")))
            subject = decode_mime_header(msg.get("Subject", "(no subject)"))
            date_str = msg.get("Date", "unknown")
            body = get_email_body(msg)

            inbox_replies.append({
                "from": from_addr,
                "from_raw": decode_mime_header(msg.get("From", "")),
                "subject": subject,
                "date": date_str,
                "body": body,
            })
    except Exception as e:
        print(f"    Warning: error searching for {addr}: {e}")

mail.logout()

# ── Print IMAP results ────────────────────────────────────────────────────

print(f"\n{'=' * 80}")
print(f"IMAP INBOX RESULTS: Found {len(inbox_replies)} email(s) from nudge recipients")
print(f"{'=' * 80}")

if inbox_replies:
    for i, reply in enumerate(inbox_replies, 1):
        print(f"\n{'─' * 80}")
        print(f"  EMAIL #{i}")
        print(f"  From:    {reply['from_raw']}")
        print(f"  Date:    {reply['date']}")
        print(f"  Subject: {reply['subject']}")
        print(f"{'─' * 80}")
        print(f"\n{reply['body']}\n")
else:
    print("\n  No new emails found in IMAP inbox from nudge recipients in the last 14 days.")

# ── Check CRM Audit Database ──────────────────────────────────────────────

print(f"\n{'=' * 80}")
print("CRM AUDIT DATABASE RESULTS")
print(f"{'=' * 80}")

conn = sqlite3.connect(AUDIT_DB)
cur = conn.cursor()

# Lead status summary
print("\n[4] Lead statuses for nudge campaign recipients:")
print(f"    {'Email':<42} {'Status':<12} {'Name'}")
print(f"    {'─' * 42} {'─' * 12} {'─' * 30}")

placeholders = ",".join(["?"] * len(NUDGE_RECIPIENTS))
cur.execute(
    f"SELECT email, status, first_name, last_name FROM leads WHERE email IN ({placeholders}) ORDER BY status, email",
    NUDGE_RECIPIENTS,
)
for row in cur.fetchall():
    email_addr, status, first, last = row
    name = f"{first or ''} {last or ''}".strip() or "(unknown)"
    print(f"    {email_addr:<42} {status or 'n/a':<12} {name}")

# Responses
print(f"\n[5] Responses recorded in CRM from nudge recipients:")
cur.execute(
    f"""
    SELECT r.id, l.email, l.first_name, l.last_name, r.received_at, r.subject, r.body, r.label, r.notes
    FROM responses r
    JOIN leads l ON r.lead_id = l.id
    WHERE l.email IN ({placeholders})
    ORDER BY r.received_at DESC
    """,
    NUDGE_RECIPIENTS,
)
responses = cur.fetchall()

if responses:
    print(f"    Found {len(responses)} response(s) in the CRM.\n")
    for resp in responses:
        rid, em, first, last, recv, subj, body, label, notes = resp
        name = f"{first or ''} {last or ''}".strip() or "(unknown)"
        print(f"  {'─' * 78}")
        print(f"  Response #{rid} from {name} <{em}>")
        print(f"  Received: {recv}")
        print(f"  Subject:  {subj}")
        print(f"  Label:    {label or '(none)'}")
        print(f"  Notes:    {notes or '(none)'}")
        print(f"  {'─' * 78}")
        # Print just the reply portion (before the quoted thread)
        if body:
            reply_text = body
            for marker in ["\nOn ", "\nOn\n", "\n>", "---------- Forwarded"]:
                idx = reply_text.find(marker)
                if idx > 0:
                    reply_text = reply_text[:idx]
                    break
            print(f"  Reply text: {reply_text.strip()}")
        print()
else:
    print("    No responses found in CRM for nudge recipients.")

# Summary of who has NOT responded
print(f"\n{'=' * 80}")
print("SUMMARY: WHO HAS NOT REPLIED?")
print(f"{'=' * 80}")

cur.execute(
    f"SELECT email FROM leads WHERE email IN ({placeholders}) AND status = 'responded'",
    NUDGE_RECIPIENTS,
)
responded_emails = {row[0] for row in cur.fetchall()}

cur.execute(
    f"SELECT email, status FROM leads WHERE email IN ({placeholders})",
    NUDGE_RECIPIENTS,
)
all_leads = {row[0]: row[1] for row in cur.fetchall()}

print(f"\n  RESPONDED ({len(responded_emails)}):")
for em in sorted(responded_emails):
    print(f"    [x] {em}")

not_responded = set(NUDGE_RECIPIENTS) - responded_emails
print(f"\n  NOT RESPONDED ({len(not_responded)}):")
for em in sorted(not_responded):
    status = all_leads.get(em, "not in CRM")
    print(f"    [ ] {em}  (status: {status})")

conn.close()

print(f"\n{'=' * 80}")
print("Done.")
print(f"{'=' * 80}")
