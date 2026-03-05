#!/usr/bin/env python3
"""
One-time fix: mark malformed email addresses as bounced.

Found during audit:
- allison.lmft@gmail.commailing  (extra "mailing" appended to domain)
- @gmail.comweatherswitness       (missing local part, extra text on domain)

These can never receive email and should be marked bounced.
"""
import sqlite3
import os

# Uses local SQLite by default; set DATABASE_URI env var for Turso/production
CRM_DB = os.path.join(os.path.dirname(__file__), "crm", "instance", "crm.db")

MALFORMED = [
    "allison.lmft@gmail.commailing",
    "@gmail.comweatherswitness",
]


def main():
    conn = sqlite3.connect(CRM_DB)
    cur = conn.cursor()

    for email in MALFORMED:
        cur.execute("SELECT id, email, status FROM leads WHERE email = ?", (email,))
        row = cur.fetchone()
        if row:
            lead_id, lead_email, status = row
            print(f"Found: id={lead_id} email={lead_email} status={status}")
            if status != "bounced":
                cur.execute("UPDATE leads SET status = 'bounced' WHERE id = ?", (lead_id,))
                print(f"  -> Marked as bounced")
            else:
                print(f"  -> Already bounced, no change")

            # Stop any active campaign_leads
            cur.execute(
                "UPDATE campaign_leads SET status = 'stopped' WHERE lead_id = ? AND status = 'active'",
                (lead_id,),
            )
            stopped = cur.rowcount
            if stopped:
                print(f"  -> Stopped {stopped} active campaign(s)")
        else:
            print(f"Not found: {email}")

    conn.commit()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
