#!/usr/bin/env python3
"""
One-time script to update Wedding Counselors email sequences with
psychology-optimized copy. Run via GitHub Actions workflow_dispatch.

Changes applied:
  - "Free permanently" framing lands before any $29/month mention
  - Explicit "no credit card, no catch" in every email
  - Deadline reframed: affects new signups, not the person receiving this email
  - Endowment effect: "your spot", "yours stays free forever once you're in"
  - "Reply yes" low-friction CTA added to emails 1 & 2
  - All emails tightened under 80 words
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_URI   = os.getenv('DATABASE_URI', '')
TURSO_TOKEN    = os.getenv('TURSO_AUTH_TOKEN', '')
TURSO_DB_URL   = DATABASE_URI.replace('libsql://', 'https://') + '/v2/pipeline'


def turso_query(sql, args=None):
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if args:
        stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(
        TURSO_DB_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data["results"][0]["response"]["result"]
    cols = [c["name"] for c in result["cols"]]
    rows = [[cell["value"] if cell["type"] != "null" else None for cell in row] for row in result["rows"]]
    return cols, rows


def turso_exec(sql, args=None):
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if args:
        stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(
        TURSO_DB_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


NEW_SEQUENCES = [
    {
        "step_number": 1,
        "subject_template": "couple inquiry in {industry} — want in?",
        "email_template": (
            "Hi {firstName|there},\n\n"
            "I'm building WeddingCounselors.com — a directory dedicated to premarital counseling. "
            "We crossed 1,500 counselors this month and we're generating leads from couples in {industry} right now.\n\n"
            "Founding member listings are free — permanently. No credit card, no catch. "
            "After {deadline}, new counselors pay $29/month. Yours stays free forever once you're in.\n\n"
            "Takes 2 minutes: https://www.weddingcounselors.com/professional/signup\n\n"
            "Or reply \"yes\" and I'll walk you through it.\n\n"
            "Sarah\n"
            "Wedding Counselors Directory"
        ),
    },
    {
        "step_number": 2,
        "subject_template": "re: couple inquiry in {industry}",
        "email_template": (
            "Quick follow-up — founding members are already getting weekly visibility reports "
            "showing real profile views and couple inquiries from people searching in their area.\n\n"
            "Your spot is still open. Free forever, no credit card. "
            "After {deadline}, new counselors pay $29/mo — that's for people who join after that date, "
            "not you once you're in.\n\n"
            "2 minutes: https://www.weddingcounselors.com/professional/signup\n\n"
            "Or reply \"yes.\"\n\n"
            "Sarah"
        ),
    },
    {
        "step_number": 3,
        "subject_template": "your free listing expires {deadline}",
        "email_template": (
            "Hi {firstName|there},\n\n"
            "Last note from me — after {deadline}, founding member listings close and new counselors pay $29/month.\n\n"
            "Your listing is free permanently once you're in. "
            "I can't extend that to anyone who signs up after {deadline}.\n\n"
            "Reply \"yes\" or sign up here: https://www.weddingcounselors.com/professional/signup\n\n"
            "Sarah"
        ),
    },
]


def main():
    print("Updating Wedding Counselors email sequences...\n")

    _, rows = turso_query(
        "SELECT id, name, status FROM campaigns WHERE name LIKE '%Wedding%' OR name LIKE '%wedding%'"
    )

    if not rows:
        print("ERROR: No Wedding Counselors campaigns found.")
        sys.exit(1)

    for row in rows:
        campaign_id, name, status = row[0], row[1], row[2]
        print(f"Campaign: {name} (ID: {campaign_id}, Status: {status})")

        for seq in NEW_SEQUENCES:
            _, existing = turso_query(
                "SELECT id, subject_template FROM sequences WHERE campaign_id = ? AND step_number = ?",
                [campaign_id, seq["step_number"]],
            )
            if existing:
                seq_id = existing[0][0]
                old_subject = existing[0][1]
                turso_exec(
                    "UPDATE sequences SET subject_template=?, email_template=? WHERE id=?",
                    [seq["subject_template"], seq["email_template"], seq_id],
                )
                print(f"  Step {seq['step_number']}: updated")
                print(f"    was: {old_subject!r}")
                print(f"    now: {seq['subject_template']!r}")
            else:
                print(f"  Step {seq['step_number']}: not found in this campaign, skipping")

    print("\nAll done.")


if __name__ == "__main__":
    if not DATABASE_URI or not TURSO_TOKEN:
        print("ERROR: DATABASE_URI and TURSO_AUTH_TOKEN must be set.")
        sys.exit(1)
    main()
