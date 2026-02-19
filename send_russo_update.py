"""
One-off: Email Dr. Russo that her login freeze has been fixed,
update her CRM status, and record in sent_emails.
Uses Turso HTTP API (no libsql build needed) + stdlib smtplib.
"""

import smtplib
import os
import json
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formataddr, formatdate
from dotenv import load_dotenv

load_dotenv()

# --- Turso HTTP API ---
TURSO_URL = os.getenv('TURSO_DATABASE_URL').replace('libsql://', 'https://') + '/v2/pipeline'
TURSO_TOKEN = os.getenv('TURSO_AUTH_TOKEN')

LEAD_ID = 65
TO_EMAIL = "dr.russotherapy@gmail.com"

BODY = """Hi Dr. Russo,

Quick update — we found the exact issue that was freezing your login. After you signed in, the page was timing out trying to load your profile and then redirecting you back to the beginning. That's been fixed now and I've tested it end to end.

Your earlier profile information is still saved. You should be able to log in here and pick up right where you left off: https://www.weddingcounselors.com/professional/signup

If anything acts up, just reply here and I'll take care of it right away.

Sarah, Wedding Counselors Directory"""


def turso_query(sql, args=None):
    """Execute a SQL query via Turso HTTP API."""
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if args:
        stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(
        TURSO_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data["results"][0]["response"]["result"]
    cols = [c["name"] for c in result["cols"]]
    rows = []
    for row in result["rows"]:
        rows.append([cell["value"] if cell["type"] != "null" else None for cell in row])
    return cols, rows


def turso_exec(sql, args=None):
    """Execute a write SQL statement via Turso HTTP API."""
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if args:
        stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(
        TURSO_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    body = BODY.strip()

    # 1. Get inbox credentials
    print("Fetching inbox credentials...")
    _, rows = turso_query(
        'SELECT email, smtp_host, smtp_port, smtp_use_tls, username, password, name, id '
        'FROM inboxes WHERE id = 1'
    )
    inbox = rows[0]
    FROM_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USE_TLS = inbox[0], inbox[1], int(inbox[2]), int(inbox[3])
    USERNAME, PASSWORD, FROM_NAME, INBOX_ID = inbox[4], inbox[5], inbox[6], inbox[7]

    # 2. Get thread info
    print("Fetching thread info...")
    _, first_rows = turso_query(
        f'SELECT message_id, subject FROM sent_emails '
        f'WHERE lead_id = {LEAD_ID} ORDER BY sent_at ASC LIMIT 1'
    )
    _, resp_rows = turso_query(
        f'SELECT message_id FROM responses '
        f'WHERE lead_id = {LEAD_ID} ORDER BY received_at DESC LIMIT 1'
    )
    _, sent_rows = turso_query(
        f'SELECT message_id FROM sent_emails '
        f'WHERE lead_id = {LEAD_ID} AND message_id IS NOT NULL '
        f'ORDER BY sent_at DESC LIMIT 1'
    )

    in_reply_to = None
    references = []

    if resp_rows and resp_rows[0][0]:
        in_reply_to = resp_rows[0][0]
        if not in_reply_to.startswith('<'):
            in_reply_to = f'<{in_reply_to}>'

    if first_rows and first_rows[0][0]:
        msgid = first_rows[0][0]
        if not msgid.startswith('<'):
            msgid = f'<{msgid}>'
        references.append(msgid)

    if resp_rows and resp_rows[0][0]:
        msgid = resp_rows[0][0]
        if not msgid.startswith('<'):
            msgid = f'<{msgid}>'
        if msgid not in references:
            references.append(msgid)

    if sent_rows and sent_rows[0][0]:
        msgid = sent_rows[0][0]
        if not msgid.startswith('<'):
            msgid = f'<{msgid}>'
        if msgid not in references:
            references.append(msgid)

    subject = first_rows[0][1] if first_rows else "founding member spot"
    if not subject.lower().startswith('re:'):
        subject = f'Re: {subject}'
    refs_str = ' '.join(references)

    print(f"  Subject: {subject}")
    print(f"  In-Reply-To: {in_reply_to}")
    print(f"  References: {refs_str[:80]}...")

    # 3. Send the email
    print(f"\nSending to Dr. Russo ({TO_EMAIL})...")
    msg = MIMEMultipart('alternative')
    msg['From'] = formataddr((FROM_NAME, FROM_EMAIL))
    msg['To'] = TO_EMAIL
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)

    message_id = make_msgid(domain=FROM_EMAIL.split('@')[1])
    msg['Message-ID'] = message_id

    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if refs_str:
        msg['References'] = refs_str

    msg.attach(MIMEText(body, 'plain'))
    body_html = body.replace('\n', '<br>')
    msg.attach(MIMEText(body_html, 'html'))

    if SMTP_USE_TLS:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)

    server.login(USERNAME, PASSWORD)
    server.sendmail(FROM_EMAIL, [TO_EMAIL], msg.as_string())
    server.quit()
    print(f"  SENT OK: {message_id}")

    # 4. Record in sent_emails
    print("Recording in database...")
    _, info_rows = turso_query(
        f'SELECT campaign_id, sequence_id FROM sent_emails WHERE lead_id = {LEAD_ID} LIMIT 1'
    )
    campaign_id = info_rows[0][0] if info_rows else '1'
    sequence_id = info_rows[0][1] if info_rows else '1'

    turso_exec(
        "INSERT INTO sent_emails (lead_id, campaign_id, sequence_id, inbox_id, "
        "message_id, subject, body, status, sent_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'sent', datetime('now'))",
        [LEAD_ID, campaign_id, sequence_id, INBOX_ID, message_id, subject, body],
    )
    print("  Recorded in DB")

    # 5. Update lead status
    print("Updating CRM status...")
    turso_exec(
        "UPDATE leads SET status = 'contacted', updated_at = datetime('now') WHERE id = ?",
        [LEAD_ID],
    )
    print("  CRM status -> 'contacted'")

    print("\nDone!")


if __name__ == "__main__":
    main()
