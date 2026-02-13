#!/usr/bin/env python3
"""
Setup RateTap restaurant outreach campaigns.

Creates:
  - 3 ratetapmx.com inboxes (camila, madison, valeria)
  - Campaign: "RateTap USA" (English, ~1,084 leads)
  - Campaign: "RateTap Mexico" (Spanish, ~101 leads)
  - 3-step email sequences per campaign (0-7-14 day cadence)
  - Inbox rotation across all 3 inboxes
  - Imports leads from FINAL_MASTER_EMAILS CSV

Uses Turso HTTP API (no libsql dependency).
"""

import os
import csv
import re
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Turso HTTP API ---
TURSO_DB_URL = os.getenv('TURSO_DATABASE_URL', '').replace('libsql://', 'https://') + '/v2/pipeline'
TURSO_TOKEN = os.getenv('TURSO_AUTH_TOKEN')
LEADS_CSV = os.path.join(os.path.dirname(__file__), '..', 'ratetapleads', 'output', 'FINAL_MASTER_EMAILS_2026-02-11.csv')

# Sources that map to Mexico campaign
MX_SOURCES = {'serp_mx'}

# --- Turso helpers (proven pattern from ceo_plays.py) ---

def turso_query(sql, args=None):
    """Execute SQL and return (cols, rows)."""
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
    rows = []
    for row in result["rows"]:
        rows.append([cell["value"] if cell["type"] != "null" else None for cell in row])
    return cols, rows


def turso_exec(sql, args=None):
    """Execute SQL without expecting rows back."""
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


def turso_batch(statements):
    """Execute multiple SQL statements in a single pipeline request."""
    reqs = []
    for sql, args in statements:
        stmt = {"type": "execute", "stmt": {"sql": sql}}
        if args:
            stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
        reqs.append(stmt)
    reqs.append({"type": "close"})
    resp = requests.post(
        TURSO_DB_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json={"requests": reqs}, timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# --- Inbox config ---

INBOXES = [
    {
        "name": "Camila",
        "email": "camila@ratetapmx.com",
        "username": "camila@ratetapmx.com",
        "password": "z7bP=00j",
    },
    {
        "name": "Madison",
        "email": "madison@ratetapmx.com",
        "username": "madison@ratetapmx.com",
        "password": "kysq0>oH",
    },
    {
        "name": "Valeria",
        "email": "valeria@ratetapmx.com",
        "username": "valeria@ratetapmx.com",
        "password": "5$u0s32S",
    },
]

# --- Email sequences ---

USA_SEQUENCES = [
    {
        "step_number": 1,
        "delay_days": 0,
        "subject_template": "google reviews for {company}",
        "email_template": """Hi there,

Quick question — how are you collecting Google reviews at {company}?

We make NFC tap cards that sit on your tables. Guests tap their phone, leave a review in 30 seconds. No app needed.

Restaurants using RateTap average 3x more Google reviews per month.

Want to see how it works? Reply and I'll send a quick demo.

RateTap
ratetapmx.com"""
    },
    {
        "step_number": 2,
        "delay_days": 7,
        "subject_template": "re: google reviews for {company}",
        "email_template": """Following up — the restaurants seeing the biggest jump in reviews are the ones catching unhappy guests before they post publicly.

When a guest taps their RateTap card, happy customers get routed to Google Reviews. Unhappy ones get routed to private feedback so your team can fix it on the spot.

Plans start at $99/month. Setup takes 10 minutes.

Worth a quick look? https://calendly.com/ratetapmx/30min

RateTap"""
    },
    {
        "step_number": 3,
        "delay_days": 7,
        "subject_template": "last note — {company}",
        "email_template": """Hi there,

Final follow-up on this. If Google reviews aren't a priority for {company} right now, no worries at all.

If they are — reply "yes" and I'll set up a 10-minute demo. No commitment.

Best,
RateTap"""
    },
]

MX_SEQUENCES = [
    {
        "step_number": 1,
        "delay_days": 0,
        "subject_template": "reseñas de Google para {company}",
        "email_template": """Hola,

Pregunta rápida — ¿cómo están recolectando reseñas de Google en {company}?

Hacemos tarjetas NFC que se ponen en las mesas. Los clientes tocan con su celular y dejan una reseña en 30 segundos. Sin descargar app.

Los restaurantes que usan RateTap obtienen 3x más reseñas de Google por mes.

¿Quieres ver cómo funciona? Responde y te mando una demo rápida.

RateTap
ratetapmx.com"""
    },
    {
        "step_number": 2,
        "delay_days": 7,
        "subject_template": "re: reseñas de Google para {company}",
        "email_template": """Seguimiento rápido — los restaurantes que más crecen en reseñas son los que detectan clientes insatisfechos antes de que publiquen en Google.

Cuando un cliente toca su tarjeta RateTap, los clientes contentos van directo a dejar reseña en Google. Los que no están contentos van a feedback privado para que tu equipo lo resuelva al momento.

Los planes empiezan en $99 USD/mes. La configuración toma 10 minutos.

¿Vale la pena una mirada rápida? https://calendly.com/ratetapmx/30min

RateTap"""
    },
    {
        "step_number": 3,
        "delay_days": 7,
        "subject_template": "último mensaje — {company}",
        "email_template": """Hola,

Último seguimiento sobre esto. Si las reseñas de Google no son prioridad para {company} ahorita, no hay problema.

Si sí lo son — responde "sí" y agendo una demo de 10 minutos. Sin compromiso.

Saludos,
RateTap"""
    },
]


# --- Lead parsing ---

def parse_restaurant_name(context: str) -> str:
    """Extract clean restaurant name from RestaurantContext field."""
    if not context:
        return ""

    name = context.strip()

    # Remove common suffixes: " - Facebook", " - Instagram", " | something", " on WhatsApp"
    for sep in [' - Facebook', ' - Instagram', ' - Yelp', ' - TripAdvisor',
                ' - Google', ' - LinkedIn', ' on WhatsApp', ' on Instagram',
                ' - VIVA LEÓN', ' - YouTube']:
        if sep in name:
            name = name.split(sep)[0].strip()

    # Handle "Name | Extra Info" — keep the part before pipe
    if ' | ' in name:
        name = name.split(' | ')[0].strip()

    # Handle "Name: Home" or "Name: Contact"
    for suffix in [': Home', ': Contact', ': Menu']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    # Handle "(City, ST)" at end
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()

    # Truncate if still too long (some have full snippets)
    if len(name) > 80:
        name = name[:77] + '...'

    return name


def load_leads(csv_path: str):
    """Load and parse leads from CSV. Returns (mx_leads, usa_leads)."""
    mx_leads = []
    usa_leads = []
    seen_emails = set()

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = (row.get('Email') or '').strip().lower()
            if not email or '@' not in email:
                continue
            if email in seen_emails:
                continue
            seen_emails.add(email)

            context = row.get('RestaurantContext', '')
            source = row.get('Source', '')
            company = parse_restaurant_name(context)

            lead = {
                'email': email,
                'company': company,
                'source': f'ratetap_{source}',
            }

            if source in MX_SOURCES:
                mx_leads.append(lead)
            else:
                usa_leads.append(lead)

    return mx_leads, usa_leads


# --- Setup functions ---

def ensure_inboxes():
    """Create or update RateTap inboxes. Returns list of inbox IDs."""
    inbox_ids = []
    for inbox_data in INBOXES:
        _, rows = turso_query(
            "SELECT id FROM inboxes WHERE email = ?",
            [inbox_data["email"]]
        )
        if rows:
            inbox_id = rows[0][0]
            turso_exec(
                """UPDATE inboxes SET username=?, password=?, smtp_host='mail.spacemail.com',
                   smtp_port=465, smtp_use_tls=0, imap_host='mail.spacemail.com',
                   imap_port=993, imap_use_ssl=1, active=1, max_per_hour=5
                   WHERE id=?""",
                [inbox_data["username"], inbox_data["password"], inbox_id]
            )
            print(f"  Updated inbox: {inbox_data['email']} (ID: {inbox_id})")
        else:
            turso_exec(
                """INSERT INTO inboxes (name, email, smtp_host, smtp_port, smtp_use_tls,
                   imap_host, imap_port, imap_use_ssl, username, password, active, max_per_hour, created_at)
                   VALUES (?, ?, 'mail.spacemail.com', 465, 0,
                   'mail.spacemail.com', 993, 1, ?, ?, 1, 5, ?)""",
                [inbox_data["name"], inbox_data["email"],
                 inbox_data["username"], inbox_data["password"],
                 datetime.utcnow().isoformat()]
            )
            _, rows = turso_query("SELECT id FROM inboxes WHERE email = ?", [inbox_data["email"]])
            inbox_id = rows[0][0]
            print(f"  Created inbox: {inbox_data['email']} (ID: {inbox_id})")

        inbox_ids.append(int(inbox_id))
    return inbox_ids


def create_campaign(name: str, primary_inbox_id: int, all_inbox_ids: list, sequences: list):
    """Create campaign with sequences and inbox rotation. Returns campaign ID."""
    # Check if campaign exists
    _, rows = turso_query("SELECT id FROM campaigns WHERE name = ?", [name])
    if rows:
        campaign_id = int(rows[0][0])
        print(f"  Campaign '{name}' already exists (ID: {campaign_id}), updating sequences...")
    else:
        turso_exec(
            """INSERT INTO campaigns (name, inbox_id, status, created_at, updated_at)
               VALUES (?, ?, 'active', ?, ?)""",
            [name, primary_inbox_id,
             datetime.utcnow().isoformat(), datetime.utcnow().isoformat()]
        )
        _, rows = turso_query("SELECT id FROM campaigns WHERE name = ?", [name])
        campaign_id = int(rows[0][0])
        print(f"  Created campaign: '{name}' (ID: {campaign_id})")

    # Set up inbox rotation
    for inbox_id in all_inbox_ids:
        _, existing = turso_query(
            "SELECT id FROM campaign_inboxes WHERE campaign_id = ? AND inbox_id = ?",
            [campaign_id, inbox_id]
        )
        if not existing:
            turso_exec(
                "INSERT INTO campaign_inboxes (campaign_id, inbox_id, added_at) VALUES (?, ?, ?)",
                [campaign_id, inbox_id, datetime.utcnow().isoformat()]
            )

    # Create/update sequences
    for seq in sequences:
        _, existing = turso_query(
            "SELECT id FROM sequences WHERE campaign_id = ? AND step_number = ?",
            [campaign_id, seq["step_number"]]
        )
        if existing:
            turso_exec(
                """UPDATE sequences SET delay_days=?, subject_template=?, email_template=?, active=1
                   WHERE campaign_id=? AND step_number=?""",
                [seq["delay_days"], seq["subject_template"], seq["email_template"],
                 campaign_id, seq["step_number"]]
            )
        else:
            turso_exec(
                """INSERT INTO sequences (campaign_id, step_number, delay_days,
                   subject_template, email_template, active, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                [campaign_id, seq["step_number"], seq["delay_days"],
                 seq["subject_template"], seq["email_template"],
                 datetime.utcnow().isoformat()]
            )
    print(f"  Configured {len(sequences)} email sequences (0-7-14 day cadence)")

    return campaign_id


def import_leads(leads: list, campaign_id: int, label: str):
    """Import leads and assign to campaign. Uses batched inserts for speed."""
    # Step 1: Get all existing emails in one query
    print(f"  [{label}] Checking {len(leads)} leads against existing database...")
    _, existing_rows = turso_query("SELECT email, id, source FROM leads")
    existing_map = {row[0]: (int(row[1]), row[2] or '') for row in existing_rows}

    # Step 2: Get all existing campaign_leads for this campaign
    _, cl_rows = turso_query(
        "SELECT lead_id FROM campaign_leads WHERE campaign_id = ?", [campaign_id]
    )
    existing_campaign_leads = {int(row[0]) for row in cl_rows}

    # Step 3: Separate leads into new inserts vs existing
    now = datetime.utcnow().isoformat()
    to_insert = []
    to_link = []  # (email, lead_id) pairs to add to campaign
    skipped_wc = 0
    skipped_dup = 0

    for lead in leads:
        if lead["email"] in existing_map:
            lead_id, source = existing_map[lead["email"]]
            if 'ratetap' not in source:
                skipped_wc += 1
                continue
            if lead_id not in existing_campaign_leads:
                to_link.append(lead_id)
            else:
                skipped_dup += 1
        else:
            to_insert.append(lead)

    # Step 4: Batch insert new leads (50 per pipeline call)
    BATCH_SIZE = 50
    inserted_count = 0

    for i in range(0, len(to_insert), BATCH_SIZE):
        batch = to_insert[i:i + BATCH_SIZE]
        stmts = []
        for lead in batch:
            stmts.append((
                """INSERT OR IGNORE INTO leads (email, company, first_name, source, status, created_at, updated_at)
                   VALUES (?, ?, '', ?, 'new', ?, ?)""",
                [lead["email"], lead["company"], lead["source"], now, now]
            ))
        turso_batch(stmts)
        inserted_count += len(batch)
        if (i + BATCH_SIZE) % 200 == 0 or i + BATCH_SIZE >= len(to_insert):
            print(f"  [{label}] Inserted {min(i + BATCH_SIZE, len(to_insert))}/{len(to_insert)} new leads...")

    # Step 5: Get IDs for all newly inserted leads
    if to_insert:
        emails_to_find = [l["email"] for l in to_insert]
        # Query in batches to avoid huge SQL
        new_lead_ids = []
        for i in range(0, len(emails_to_find), 100):
            batch_emails = emails_to_find[i:i + 100]
            placeholders = ','.join(['?' for _ in batch_emails])
            _, rows = turso_query(
                f"SELECT id FROM leads WHERE email IN ({placeholders})",
                batch_emails
            )
            new_lead_ids.extend([int(row[0]) for row in rows])
        to_link.extend(new_lead_ids)

    # Step 6: Batch insert campaign_leads
    linked_count = 0
    link_batch = [(lid) for lid in to_link if lid not in existing_campaign_leads]
    for i in range(0, len(link_batch), BATCH_SIZE):
        batch = link_batch[i:i + BATCH_SIZE]
        stmts = []
        for lead_id in batch:
            stmts.append((
                "INSERT OR IGNORE INTO campaign_leads (campaign_id, lead_id, status, added_at) VALUES (?, ?, 'active', ?)",
                [campaign_id, lead_id, now]
            ))
        turso_batch(stmts)
        linked_count += len(batch)

    print(f"  [{label}] Imported {inserted_count} new leads, linked {linked_count} to campaign")
    if skipped_wc:
        print(f"  [{label}] {skipped_wc} leads skipped (belong to Wedding Counselors)")
    if skipped_dup:
        print(f"  [{label}] {skipped_dup} leads already in campaign")

    return linked_count


# --- Main ---

def main():
    print("=" * 60)
    print("RateTap Restaurant Outreach — Campaign Setup")
    print("=" * 60)

    # Verify Turso connection
    print("\n1. Verifying Turso connection...")
    try:
        _, rows = turso_query("SELECT COUNT(*) FROM leads")
        total_leads = rows[0][0]
        print(f"   Connected. Database has {total_leads} existing leads.")
    except Exception as e:
        print(f"   ERROR: Cannot connect to Turso: {e}")
        sys.exit(1)

    # Set up inboxes
    print("\n2. Setting up RateTap inboxes...")
    inbox_ids = ensure_inboxes()
    print(f"   Inbox IDs: {inbox_ids}")

    # Load leads from CSV
    print(f"\n3. Loading leads from CSV...")
    mx_leads, usa_leads = load_leads(LEADS_CSV)
    print(f"   Mexico leads: {len(mx_leads)}")
    print(f"   USA leads: {len(usa_leads)}")

    # Create USA campaign
    print("\n4. Creating RateTap USA campaign (English)...")
    usa_campaign_id = create_campaign(
        name="RateTap USA Outreach",
        primary_inbox_id=inbox_ids[0],  # camila as primary
        all_inbox_ids=inbox_ids,
        sequences=USA_SEQUENCES,
    )

    # Create Mexico campaign
    print("\n5. Creating RateTap Mexico campaign (Spanish)...")
    mx_campaign_id = create_campaign(
        name="RateTap Mexico Outreach",
        primary_inbox_id=inbox_ids[0],
        all_inbox_ids=inbox_ids,
        sequences=MX_SEQUENCES,
    )

    # Import leads
    print("\n6. Importing leads...")
    usa_count = import_leads(usa_leads, usa_campaign_id, "USA")
    mx_count = import_leads(mx_leads, mx_campaign_id, "MX")

    # Verify
    print("\n7. Verifying setup...")
    _, rows = turso_query("SELECT id, name, status FROM campaigns WHERE name LIKE 'RateTap%'")
    for row in rows:
        _, lead_count = turso_query(
            "SELECT COUNT(*) FROM campaign_leads WHERE campaign_id = ? AND status = 'active'",
            [row[0]]
        )
        _, seq_count = turso_query(
            "SELECT COUNT(*) FROM sequences WHERE campaign_id = ? AND active = 1",
            [row[0]]
        )
        print(f"   Campaign: {row[1]} | Status: {row[2]} | "
              f"Active Leads: {lead_count[0][0]} | Sequences: {seq_count[0][0]}")

    _, inbox_rows = turso_query(
        "SELECT email, max_per_hour, active FROM inboxes WHERE email LIKE '%ratetapmx.com'"
    )
    for row in inbox_rows:
        print(f"   Inbox: {row[0]} | Rate: {row[1]}/hr | Active: {row[2]}")

    # Summary
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"\nRateTap USA:    {usa_count} leads, 3-step English sequence")
    print(f"RateTap Mexico: {mx_count} leads, 3-step Spanish sequence")
    print(f"Inboxes:        {len(inbox_ids)} rotating (camila, madison, valeria)")
    print(f"Cadence:        Day 0 → Day 7 → Day 14")
    print(f"Rate limit:     5/hour/inbox = ~120/day across 3 inboxes")
    print(f"\nBoth campaigns are ACTIVE. The GitHub Actions cron will")
    print(f"start sending on the next hourly run during business hours.")
    print(f"\nIMPORTANT: Bump DAILY_SEND_CAP in .env and GitHub Actions")
    print(f"workflow to handle the increased volume.")


if __name__ == "__main__":
    main()
