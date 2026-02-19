"""
CEO Plays - 5 Immediate Growth Moves
=====================================
1. Reply to Chris & Cara (couple inquiry from Jan 18)
2. Reply to Julie Hisrich (couple inquiry)
3. Update outreach templates with scarcity/urgency framing
4. Prepare gift lead routing (ready when couple replies with location)
5. Send March 15 monetization deadline to all engaged counselors
"""

import smtplib
import os
import json
import requests
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formataddr, formatdate
from dotenv import load_dotenv

load_dotenv()

# --- Turso HTTP API ---
TURSO_URL = os.getenv('TURSO_DATABASE_URL', '').replace('libsql://', 'https://') + '/v2/pipeline'
TURSO_TOKEN = os.getenv('TURSO_AUTH_TOKEN')

# --- SMTP state ---
_inbox = None


def turso_query(sql, args=None):
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if args:
        stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(
        TURSO_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=15,
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
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if args:
        stmt["stmt"]["args"] = [{"type": "text", "value": str(a)} for a in args]
    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(
        TURSO_URL,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_inbox():
    global _inbox
    if _inbox:
        return _inbox
    _, rows = turso_query(
        'SELECT email, smtp_host, smtp_port, smtp_use_tls, username, password, name, id '
        'FROM inboxes WHERE id = 1'
    )
    _inbox = {
        "email": rows[0][0], "smtp_host": rows[0][1], "smtp_port": int(rows[0][2]),
        "smtp_use_tls": int(rows[0][3]), "username": rows[0][4], "password": rows[0][5],
        "name": rows[0][6], "id": rows[0][7],
    }
    return _inbox


def send_email(to_email, subject, body_text, from_name=None, in_reply_to=None, references=None):
    """Send an email via inbox 1 SMTP. Returns message_id."""
    inbox = get_inbox()
    if from_name is None:
        from_name = inbox["name"]

    msg = MIMEMultipart('alternative')
    msg['From'] = formataddr((from_name, inbox["email"]))
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)

    message_id = make_msgid(domain=inbox["email"].split('@')[1])
    msg['Message-ID'] = message_id

    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = references

    msg.attach(MIMEText(body_text, 'plain'))
    body_html = body_text.replace('\n\n', '</p><p>').replace('\n', '<br>')
    body_html = f'<p>{body_html}</p>'
    msg.attach(MIMEText(body_html, 'html'))

    if inbox["smtp_use_tls"]:
        server = smtplib.SMTP(inbox["smtp_host"], inbox["smtp_port"], timeout=30)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(inbox["smtp_host"], inbox["smtp_port"], timeout=30)

    server.login(inbox["username"], inbox["password"])
    server.sendmail(inbox["email"], [to_email], msg.as_string())
    server.quit()

    return message_id


def get_thread_info(lead_id):
    """Get threading headers for an existing conversation."""
    _, first_rows = turso_query(
        f'SELECT message_id, subject FROM sent_emails '
        f'WHERE lead_id = {lead_id} ORDER BY sent_at ASC LIMIT 1'
    )
    _, resp_rows = turso_query(
        f'SELECT message_id FROM responses '
        f'WHERE lead_id = {lead_id} ORDER BY received_at DESC LIMIT 1'
    )
    _, sent_rows = turso_query(
        f'SELECT message_id FROM sent_emails '
        f'WHERE lead_id = {lead_id} AND message_id IS NOT NULL '
        f'ORDER BY sent_at DESC LIMIT 1'
    )

    in_reply_to = None
    references = []

    if resp_rows and resp_rows[0][0]:
        in_reply_to = resp_rows[0][0]
        if not in_reply_to.startswith('<'):
            in_reply_to = f'<{in_reply_to}>'

    if first_rows and first_rows[0][0]:
        msgid = first_rows[0][0] if first_rows[0][0].startswith('<') else f'<{first_rows[0][0]}>'
        references.append(msgid)
    if resp_rows and resp_rows[0][0]:
        msgid = resp_rows[0][0] if resp_rows[0][0].startswith('<') else f'<{resp_rows[0][0]}>'
        if msgid not in references:
            references.append(msgid)
    if sent_rows and sent_rows[0][0]:
        msgid = sent_rows[0][0] if sent_rows[0][0].startswith('<') else f'<{sent_rows[0][0]}>'
        if msgid not in references:
            references.append(msgid)

    subject = first_rows[0][1] if first_rows else "founding member spot"
    if not subject.lower().startswith('re:'):
        subject = f'Re: {subject}'

    return in_reply_to, ' '.join(references), subject


# ============================================================
# PLAY 1: Reply to Chris & Cara
# ============================================================
def play_1():
    print("=" * 60)
    print("PLAY 1: Reply to Chris & Cara")
    print("=" * 60)

    to = "caralynandchristopher@gmail.com"
    subject = "your premarital counseling inquiry"
    body = """Hi Chris and Cara,

I'm Lawrence, the founder of Wedding Counselors. I'm so sorry for the delayed response — we were upgrading our matching system.

I'd love to personally connect you with 2-3 premarital counselors in your area who specialize in faith-based counseling. Can you tell me your city and state? We'll have recommendations for you within 24 hours.

Lawrence
Wedding Counselors Directory
weddingcounselors.com""".strip()

    mid = send_email(to, subject, body, from_name="Lawrence from Wedding Counselors")
    print(f"  SENT to {to}")
    print(f"  Subject: {subject}")
    print(f"  Message-ID: {mid}")
    print()
    return mid


# ============================================================
# PLAY 2: Reply to Julie Hisrich
# ============================================================
def play_2():
    print("=" * 60)
    print("PLAY 2: Reply to Julie Hisrich")
    print("=" * 60)

    to = "jhisrich17@gmail.com"
    subject = "your counseling inquiry"
    body = """Hi Julie,

I'm Lawrence, the founder of Wedding Counselors. I saw your inquiry about finding a Catholic therapist for your daughter — I'd love to help.

We work with faith-based counselors nationwide and can connect you with qualified professionals in your area. Can you share your city and state? I'll personally send you 2-3 recommendations.

Lawrence
Wedding Counselors Directory
weddingcounselors.com""".strip()

    mid = send_email(to, subject, body, from_name="Lawrence from Wedding Counselors")
    print(f"  SENT to {to}")
    print(f"  Subject: {subject}")
    print(f"  Message-ID: {mid}")
    print()
    return mid


# ============================================================
# PLAY 3: Update outreach templates with scarcity framing
# ============================================================
def play_3():
    print("=" * 60)
    print("PLAY 3: Update outreach sequence templates")
    print("=" * 60)

    # New sequence templates with CEO positioning
    seq1_subject = "couple inquiry in {industry} — want in?"
    seq1_body = """Hi {firstName|there},

I'm building WeddingCounselors.com, the first directory dedicated to premarital counseling. We just crossed 1,500 counselors and started receiving couple inquiries this month.

We're offering free founding member listings through March 15. After that, listings will be $29/month. Founding members keep their free listing permanently.

Takes 2 minutes: https://www.weddingcounselors.com/professional/signup

Sarah
Wedding Counselors Directory
weddingcounselors.com | 2108 N St NW, Washington DC 20037"""

    seq2_subject = "re: couple inquiry in {industry}"
    seq2_body = """Quick follow-up — our founding members just started getting weekly visibility reports showing their profile views and couple inquiries.

Free founding member spots close March 15. After that it's $29/mo.

Worth a look? https://www.weddingcounselors.com/professional/signup

Sarah
weddingcounselors.com"""

    seq3_subject = "closing founding spots march 15"
    seq3_body = """Hi {firstName|there},

Last note on this. Free founding member listings close March 15 — after that it's $29/month.

Founding members keep their listing free permanently and get priority placement when couples search in {industry}.

Reply "yes" if you want in before we close it.

Sarah
weddingcounselors.com"""

    # Get Campaign 2 sequences
    _, seq_rows = turso_query(
        "SELECT id, step_number FROM sequences WHERE campaign_id = 2 ORDER BY step_number ASC"
    )

    if seq_rows:
        templates = [
            (seq1_subject, seq1_body),
            (seq2_subject, seq2_body),
            (seq3_subject, seq3_body),
        ]
        for i, row in enumerate(seq_rows):
            if i < len(templates):
                seq_id = row[0]
                turso_exec(
                    "UPDATE sequences SET subject_template = ?, email_template = ? WHERE id = ?",
                    [templates[i][0], templates[i][1], seq_id],
                )
                print(f"  Updated sequence {row[1]} (id={seq_id}): {templates[i][0]}")

        # Activate the campaign
        turso_exec("UPDATE campaigns SET status = 'active' WHERE id = 2")
        print("  Campaign 2 status -> 'active'")
    else:
        # Create sequences if they don't exist
        print("  No sequences found for Campaign 2 — creating them...")
        for step, (subj, body), delay in zip(
            [1, 2, 3],
            [(seq1_subject, seq1_body), (seq2_subject, seq2_body), (seq3_subject, seq3_body)],
            [0, 7, 7],
        ):
            turso_exec(
                "INSERT INTO sequences (campaign_id, step_number, delay_days, "
                "subject_template, email_template, active) VALUES (2, ?, ?, ?, ?, 1)",
                [step, delay, subj, body],
            )
            print(f"  Created sequence step {step}: {subj}")

    print()


# ============================================================
# PLAY 4: Gift lead routing setup
# ============================================================

FOUNDING_MEMBERS = [
    {"lead_id": 21, "name": "Dr. Robin Bryant", "email": "robinbryant134@gmail.com", "state": "New York"},
    {"lead_id": 28, "name": "Dr. Mira Svatovic", "email": "thecouplespractice@gmail.com", "state": "New York"},
    {"lead_id": 65, "name": "Dr. Deborah Russo", "email": "dr.russotherapy@gmail.com", "state": "Georgia"},
    {"lead_id": 91, "name": "Anastasia Brown", "email": "annaholdingscompany@gmail.com", "state": "Louisiana"},
    {"lead_id": 25, "name": "Jim Walkup", "email": "jimwalkup@gmail.com", "state": "Unknown"},
    {"lead_id": 110, "name": "Jim Brazel", "email": "jimbwmwg@gmail.com", "state": "Michigan"},
    {"lead_id": 116, "name": "Sarah Kenville", "email": "enrichyourrelationship@gmail.com", "state": "Minnesota"},
    {"lead_id": 138, "name": "Dr. Frank MacArthur", "email": "frankmacarthurpsyd@gmail.com", "state": "New Jersey"},
    {"lead_id": 177, "name": "Pamela Price-Lerner", "email": "therapywithpamela@gmail.com", "state": "Vermont"},
    {"lead_id": 206, "name": "Dr. William Ryan", "email": "drwilliamryan@gmail.com", "state": "Unknown"},
    {"lead_id": 180, "name": "Min. April Brown", "email": "maritalminister@gmail.com", "state": "Virginia"},
    {"lead_id": 190, "name": "Amanda Augustenborg", "email": "amandaaugustenborg@gmail.com", "state": "Unknown"},
    {"lead_id": 236, "name": "Martha Maurno", "email": "boxelderbehavioralhealth@gmail.com", "state": "Unknown"},
    {"lead_id": 241, "name": "Anthony Thomas", "email": "anthonythomas.lcsw@gmail.com", "state": "North Carolina"},
    {"lead_id": 283, "name": "Britney (Sparrow)", "email": "sparrowcounselingonline@gmail.com", "state": "Washington"},
    {"lead_id": 161, "name": "Jeffrey Adorador", "email": "jadoradorlmft@gmail.com", "state": "Unknown"},
]


def play_4():
    print("=" * 60)
    print("PLAY 4: Gift Lead Routing — READY")
    print("=" * 60)
    print()
    print("  When Chris & Cara reply with their city/state, run:")
    print("    python -c \"from ceo_plays import send_gift_lead; send_gift_lead('STATE', 'Chris and Cara', 'caralynandchristopher@gmail.com', 'faith-based premarital counseling')\"")
    print()
    print("  Founding members by state:")
    by_state = {}
    for m in FOUNDING_MEMBERS:
        by_state.setdefault(m["state"], []).append(m["name"])
    for state, names in sorted(by_state.items()):
        print(f"    {state}: {', '.join(names)}")
    print()


def send_gift_lead(state, couple_name, couple_email, looking_for):
    """Send a gift lead to the nearest founding member."""
    matches = [m for m in FOUNDING_MEMBERS if m["state"].lower() == state.lower()]
    if not matches:
        print(f"  No founding member in {state}. Closest options:")
        for m in FOUNDING_MEMBERS:
            if m["state"] != "Unknown":
                print(f"    {m['name']} — {m['state']}")
        return

    for member in matches:
        in_reply_to, references, subject = get_thread_info(member["lead_id"])

        body = f"""Hi {member['name'].split()[-1]},

We just received an inquiry from an engaged couple in {state} looking for {looking_for}. I'm personally sending this to you because you're one of our founding members.

Here are their details:
- Name: {couple_name}
- Email: {couple_email}
- Looking for: {looking_for}

Feel free to reach out to them directly. This is on us — one of the perks of being a founding member.

Sarah, Wedding Counselors Directory""".strip()

        mid = send_email(member["email"], subject, body, in_reply_to=in_reply_to, references=references)
        print(f"  Gift lead sent to {member['name']} ({member['email']}): {mid}")


# ============================================================
# PLAY 5: March 15 monetization deadline broadcast
# ============================================================
def play_5():
    print("=" * 60)
    print("PLAY 5: March 15 Monetization Deadline Broadcast")
    print("=" * 60)

    for i, member in enumerate(FOUNDING_MEMBERS):
        lead_id = member["lead_id"]
        to_email = member["email"]
        name = member["name"]

        # Get first name for personalization
        first = name.split()[0]
        if first in ("Dr.", "Min."):
            first = name  # Keep formal for titled professionals

        in_reply_to, references, subject = get_thread_info(lead_id)

        body = f"""Hi {first},

Quick update — we resolved the technical issues on the platform that some of you hit during signup. Everything is working smoothly now.

More importantly: free founding member listings close March 15. After that, new counselors pay $29/month.

As a founding member, your listing stays free forever. That's locked in. If you haven't completed your profile yet, you can do it here in about 2 minutes: https://www.weddingcounselors.com/professional/signup

We're also rolling out weekly visibility reports and adding premium features — priority placement, analytics dashboard, and lead alerts — available as an optional upgrade in the coming weeks.

Thanks for being part of this from the start.

Sarah, Wedding Counselors Directory""".strip()

        try:
            mid = send_email(to_email, subject, body, in_reply_to=in_reply_to, references=references)
            print(f"  [{i+1}/{len(FOUNDING_MEMBERS)}] SENT to {name} ({to_email}): {mid}")

            # Record in DB
            _, info_rows = turso_query(
                f'SELECT campaign_id, sequence_id FROM sent_emails WHERE lead_id = {lead_id} LIMIT 1'
            )
            campaign_id = info_rows[0][0] if info_rows else '2'
            sequence_id = info_rows[0][1] if info_rows else '1'

            turso_exec(
                "INSERT INTO sent_emails (lead_id, campaign_id, sequence_id, inbox_id, "
                "message_id, subject, body, status, sent_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'sent', datetime('now'))",
                [lead_id, campaign_id, sequence_id, get_inbox()["id"], mid, subject, body],
            )
        except Exception as e:
            print(f"  [{i+1}/{len(FOUNDING_MEMBERS)}] ERROR {name}: {e}")

        if i < len(FOUNDING_MEMBERS) - 1:
            time.sleep(3)

    print()


# ============================================================
# MAIN
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("  CEO PLAYS — EXECUTING ALL 5 MOVES")
    print("=" * 60 + "\n")

    print("Fetching inbox credentials...")
    get_inbox()
    print(f"  Using: {_inbox['email']}\n")

    mid1 = play_1()
    time.sleep(3)

    mid2 = play_2()
    time.sleep(3)

    play_3()

    play_4()

    play_5()

    print("=" * 60)
    print("  ALL 5 PLAYS COMPLETE")
    print("=" * 60)
    print(f"""
NEXT STEPS:
  1. Watch for Chris & Cara reply → run gift lead routing (Play 4)
  2. Watch for Julie's reply → connect her with counselors
  3. New outreach uses updated templates automatically
  4. March 15 deadline is now live — enforce it
  5. Start charging $29/mo on March 16 for new signups
""")


if __name__ == "__main__":
    main()
