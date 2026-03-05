#!/usr/bin/env python3
"""
Verify outbound email health for a given day.

Checks:
- Sent count from IMAP Sent folder
- Inbound replies since date (and which are from today's recipients)
- Bounce/complaint-like messages in inbox folders
- New signup indicators from Supabase (profiles + auth users)
"""
import argparse
import email
import imaplib
import os
import sqlite3
import sys
import urllib.parse
from datetime import datetime, date, timezone
from email.header import decode_header
from email.utils import getaddresses
from typing import Optional

import requests
from dotenv import load_dotenv


DB_PATH = os.path.join(os.path.dirname(__file__), "crm", "instance", "crm.db")
DOTENV_PATH = os.path.join(os.path.dirname(__file__), "crm", ".env")
IMAP_HOST = "mail.spacemail.com"
IMAP_PORT = 993
SENDER_EMAIL = "hello@weddingcounselors.com"

BOUNCE_SUBJECT_TOKENS = (
    "undeliverable",
    "delivery status notification",
    "mail delivery failed",
    "delivery failure",
    "returned mail",
    "failure notice",
    "spam complaint",
    "complaint",
)

BOUNCE_SENDER_TOKENS = (
    "mailer-daemon",
    "postmaster",
    "mail delivery subsystem",
    "abuse@",
)


def decode_mime(value: str) -> str:
    if not value:
        return ""
    output = []
    for part, enc in decode_header(value):
        if isinstance(part, bytes):
            output.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            output.append(part)
    return "".join(output)


def get_credentials() -> tuple[str, str]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT username, password FROM inboxes WHERE email = ?", (SENDER_EMAIL,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise RuntimeError(f"Inbox credentials not found for {SENDER_EMAIL}")
    return row[0], row[1]


def search_ids(mail: imaplib.IMAP4_SSL, criteria: str) -> list[bytes]:
    status, data = mail.search(None, criteria)
    if status != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def fetch_headers(mail: imaplib.IMAP4_SSL, message_id: bytes) -> Optional[email.message.Message]:
    status, msg_data = mail.fetch(message_id, "(RFC822.HEADER)")
    if status != "OK" or not msg_data or not msg_data[0]:
        return None
    return email.message_from_bytes(msg_data[0][1])


def parse_recipient_addresses(to_header: str) -> list[str]:
    addresses = []
    for _, addr in getaddresses([to_header]):
        addr = (addr or "").strip().lower()
        if addr:
            addresses.append(addr)
    return addresses


def fetch_sent(mail: imaplib.IMAP4_SSL, on_date: str):
    mail.select("Sent")
    sent_ids = search_ids(mail, f"ON {on_date}")
    rows = []
    recipient_set = set()
    for msg_id in sent_ids:
        msg = fetch_headers(mail, msg_id)
        if not msg:
            continue
        to_header = msg.get("To", "")
        recipients = parse_recipient_addresses(to_header)
        recipient_set.update(recipients)
        rows.append(
            {
                "date": msg.get("Date", ""),
                "to": to_header,
                "subject": decode_mime(msg.get("Subject", "")),
                "message_id": (msg.get("Message-ID", "") or "").strip("<>"),
            }
        )
    return rows, recipient_set


def fetch_inbound(mail: imaplib.IMAP4_SSL, since_date: str):
    mail.select("INBOX")
    inbound_ids = search_ids(mail, f"SINCE {since_date}")
    rows = []
    for msg_id in inbound_ids:
        msg = fetch_headers(mail, msg_id)
        if not msg:
            continue
        from_addr = ""
        parsed = getaddresses([msg.get("From", "")])
        if parsed and parsed[0][1]:
            from_addr = parsed[0][1].strip().lower()
        rows.append(
            {
                "from_email": from_addr,
                "from_header": decode_mime(msg.get("From", "")),
                "subject": decode_mime(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "in_reply_to": (msg.get("In-Reply-To", "") or "").strip("<>"),
            }
        )
    return rows


def fetch_bounce_like(mail: imaplib.IMAP4_SSL, since_date: str):
    status, boxes = mail.list()
    if status != "OK":
        return []

    folders = []
    for row in boxes or []:
        line = row.decode(errors="ignore")
        folders.append(line.split(' "/" ')[-1].strip('"'))

    findings = []
    for folder in folders:
        sel, _ = mail.select(folder)
        if sel != "OK":
            continue
        ids = search_ids(mail, f"SINCE {since_date}")
        for msg_id in ids:
            msg = fetch_headers(mail, msg_id)
            if not msg:
                continue
            from_header = decode_mime(msg.get("From", ""))
            subject = decode_mime(msg.get("Subject", ""))
            from_l = from_header.lower()
            subject_l = subject.lower()
            if any(t in from_l for t in BOUNCE_SENDER_TOKENS) or any(
                t in subject_l for t in BOUNCE_SUBJECT_TOKENS
            ):
                findings.append(
                    {
                        "folder": folder,
                        "date": msg.get("Date", ""),
                        "from": from_header,
                        "subject": subject,
                    }
                )
    return findings


def supabase_counts(day_start_utc_iso: str) -> dict:
    load_dotenv(DOTENV_PATH)
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""

    if not url or not key:
        return {"configured": False}

    base = f"{url}/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    profiles_url = (
        f"{base}/profiles?select=id,email,created_at,is_claimed&"
        f"created_at=gte.{urllib.parse.quote(day_start_utc_iso, safe='')}"
    )
    profiles_resp = requests.get(profiles_url, headers=headers, timeout=20)
    profiles = profiles_resp.json() if profiles_resp.status_code == 200 else []

    auth_url = f"{url}/auth/v1/admin/users?page=1&per_page=1000"
    auth_resp = requests.get(
        auth_url,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=20,
    )
    auth_users = auth_resp.json().get("users", []) if auth_resp.status_code == 200 else []
    auth_today = [u for u in auth_users if (u.get("created_at") or "") >= day_start_utc_iso]

    return {
        "configured": True,
        "profiles_new": len(profiles),
        "profiles_claimed_new": len([p for p in profiles if p.get("is_claimed")]),
        "auth_users_new": len(auth_today),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help="Date in YYYY-MM-DD (default: local today)",
        default=date.today().isoformat(),
    )
    args = parser.parse_args()

    try:
        target_day = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print("Invalid --date. Use YYYY-MM-DD.")
        sys.exit(1)

    imap_on = target_day.strftime("%d-%b-%Y")
    day_start_utc = datetime(
        target_day.year, target_day.month, target_day.day, tzinfo=timezone.utc
    ).isoformat().replace("+00:00", "Z")

    username, password = get_credentials()
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
    mail.login(username, password)

    sent_rows, recipients = fetch_sent(mail, imap_on)
    inbound_rows = fetch_inbound(mail, imap_on)
    bounce_rows = fetch_bounce_like(mail, imap_on)
    mail.logout()

    reply_like = [r for r in inbound_rows if r["in_reply_to"]]
    from_today_recipients = [r for r in inbound_rows if r["from_email"] in recipients]

    supabase = supabase_counts(day_start_utc)

    print("=" * 80)
    print(f"EMAIL HEALTH CHECK for {target_day.isoformat()}")
    print("=" * 80)
    print(f"Sent messages (Sent folder): {len(sent_rows)}")
    print(f"Inbound messages since date: {len(inbound_rows)}")
    print(f"Inbound replies (In-Reply-To): {len(reply_like)}")
    print(f"Inbound from today's recipients: {len(from_today_recipients)}")
    print(f"Bounce/complaint-like messages: {len(bounce_rows)}")
    if supabase.get("configured"):
        print(f"Supabase profiles created: {supabase['profiles_new']}")
        print(f"Supabase claimed profiles created: {supabase['profiles_claimed_new']}")
        print(f"Supabase auth users created: {supabase['auth_users_new']}")
    else:
        print("Supabase checks: skipped (missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY)")

    if from_today_recipients:
        print("\nReplies from today's recipients:")
        for row in from_today_recipients[:10]:
            print(f"- {row['date']} | {row['from_email']} | {row['subject']}")

    if bounce_rows:
        print("\nBounce/complaint-like findings:")
        for row in bounce_rows[:10]:
            print(f"- {row['folder']} | {row['date']} | {row['from']} | {row['subject']}")


if __name__ == "__main__":
    main()
