"""
Send personalized bump/follow-up emails to counselors who showed interest
but haven't completed signup yet. Replies are threaded into the existing
email conversation using In-Reply-To and References headers.
"""

import smtplib
import time
import libsql_experimental as libsql
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formataddr, formatdate
from dotenv import load_dotenv

load_dotenv()

# --- Database connection ---
url = os.getenv('TURSO_DATABASE_URL')
token = os.getenv('TURSO_AUTH_TOKEN')
conn = libsql.connect('temp_bump.db', sync_url=url, auth_token=token)
conn.sync()

# --- Inbox credentials ---
inbox = conn.execute(
    'SELECT email, smtp_host, smtp_port, smtp_use_tls, username, password, name, id '
    'FROM inboxes WHERE id = 1'
).fetchone()

FROM_EMAIL = inbox[0]
SMTP_HOST = inbox[1]
SMTP_PORT = inbox[2]
SMTP_USE_TLS = inbox[3]
USERNAME = inbox[4]
PASSWORD = inbox[5]
FROM_NAME = inbox[6]
INBOX_ID = inbox[7]


def get_thread_info(lead_id):
    """Get message IDs needed for threading the reply."""
    # Original outreach message ID
    first = conn.execute(
        f'SELECT message_id, subject FROM sent_emails '
        f'WHERE lead_id = {lead_id} ORDER BY sent_at ASC LIMIT 1'
    ).fetchone()

    # Most recent response from them
    last_resp = conn.execute(
        f'SELECT message_id FROM responses '
        f'WHERE lead_id = {lead_id} ORDER BY received_at DESC LIMIT 1'
    ).fetchone()

    # Most recent email we sent (may have a message_id)
    last_sent = conn.execute(
        f'SELECT message_id FROM sent_emails '
        f'WHERE lead_id = {lead_id} AND message_id IS NOT NULL '
        f'ORDER BY sent_at DESC LIMIT 1'
    ).fetchone()

    # For In-Reply-To, use the last response message_id (replying to THEM)
    # For References, chain: original outreach -> last response -> last sent
    in_reply_to = None
    references = []

    if last_resp and last_resp[0]:
        in_reply_to = last_resp[0]
        if not in_reply_to.startswith('<'):
            in_reply_to = f'<{in_reply_to}>'

    if first and first[0]:
        msgid = first[0] if first[0].startswith('<') else f'<{first[0]}>'
        references.append(msgid)

    if last_resp and last_resp[0]:
        msgid = last_resp[0] if last_resp[0].startswith('<') else f'<{last_resp[0]}>'
        if msgid not in references:
            references.append(msgid)

    if last_sent and last_sent[0]:
        msgid = last_sent[0] if last_sent[0].startswith('<') else f'<{last_sent[0]}>'
        if msgid not in references:
            references.append(msgid)

    subject = first[1] if first else "founding member spot"
    # Ensure Re: prefix
    if not subject.lower().startswith('re:'):
        subject = f'Re: {subject}'

    return in_reply_to, ' '.join(references), subject


def send_threaded_reply(to_email, subject, body_text, in_reply_to, references):
    """Send an email threaded into an existing conversation."""
    msg = MIMEMultipart('alternative')
    msg['From'] = formataddr((FROM_NAME, FROM_EMAIL))
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)

    message_id = make_msgid(domain=FROM_EMAIL.split('@')[1])
    msg['Message-ID'] = message_id

    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = references

    # Plain text
    msg.attach(MIMEText(body_text, 'plain'))
    # HTML version
    body_html = body_text.replace('\n', '<br>')
    msg.attach(MIMEText(body_html, 'html'))

    # Connect and send
    if SMTP_USE_TLS:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)

    server.login(USERNAME, PASSWORD)
    server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
    server.quit()

    return message_id


def record_sent(lead_id, message_id, subject, body):
    """Record the sent email in the database."""
    # Get campaign/sequence info from existing sent emails
    info = conn.execute(
        f'SELECT campaign_id, sequence_id FROM sent_emails '
        f'WHERE lead_id = {lead_id} LIMIT 1'
    ).fetchone()
    campaign_id = info[0] if info else 1
    sequence_id = info[1] if info else 1

    conn.execute(
        "INSERT INTO sent_emails (lead_id, campaign_id, sequence_id, inbox_id, "
        "message_id, subject, body, status, sent_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'sent', datetime('now'))",
        (lead_id, campaign_id, sequence_id, INBOX_ID, message_id, subject, body),
    )
    conn.commit()
    conn.sync()


# ============================================================
# PERSONALIZED BUMP EMAILS
# Each one references their specific conversation & situation
# ============================================================

BUMPS = [
    # 1. Dr. Robin Bryant - said "Yes. What do I need to do?" on Feb 4, got signup steps Feb 7
    {
        "lead_id": 21,
        "to": "robinbryant134@gmail.com",
        "name": "Dr. Bryant",
        "body": """Hi Dr. Bryant,

Just following up on this — I realized we had a couple bugs on the signup flow when I first sent you the link that may have caused issues. Those are all fixed now.

The whole process takes about 2 minutes and the dashboard is live so you can see your profile views and inquiries right away once you're set up.

Here's the direct link: https://www.weddingcounselors.com/professional/signup

Let me know if you run into anything.

Sarah, Wedding Counselors Directory"""
    },

    # 2. Dr. Mira Svatovic - asked "What does it require?" on Feb 5, got answer Feb 7
    {
        "lead_id": 28,
        "to": "thecouplespractice@gmail.com",
        "name": "Dr. Svatovic",
        "body": """Hi Dr. Svatovic,

Quick follow-up — we had some technical issues on the signup page when I last wrote you, which have since been fixed. Everything runs smoothly now.

It still takes about 2 minutes: create your account, verify email, fill in the basics. Your dashboard goes live immediately so you can track views and inquiries from day one.

Here's the link whenever you're ready: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 3. Dr. Deborah Russo - CRITICAL: tried to sign up, site broke multiple times
    {
        "lead_id": 65,
        "to": "dr.russotherapy@gmail.com",
        "name": "Dr. Russo",
        "body": """Hi Dr. Russo,

I owe you an update. The signup and login issues you ran into have been identified and fixed — the whole flow has been rebuilt. I'm sorry it was such a frustrating experience, especially after you took the time to start filling in your profile.

Your earlier information should still be saved. You can try logging in again here: https://www.weddingcounselors.com/professional/signup

If the login still gives you any trouble, just reply to this email and I'll sort it out personally. You were one of the first counselors to sign up and I want to make sure your profile goes live.

Sarah, Wedding Counselors Directory"""
    },

    # 4. Anastasia Brown - said "Yes, that would be great" Feb 6, got steps Feb 7
    {
        "lead_id": 91,
        "to": "annaholdingscompany@gmail.com",
        "name": "Anastasia",
        "body": """Hi Anastasia,

Following up on this — we had a couple bugs in the signup process when I sent you the link, which have since been resolved. The flow is straightforward now and takes about 2 minutes.

Once you're set up, your dashboard goes live immediately — you can see profile views and any inquiries from couples in your area.

Here's the link: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 5. Jim Walkup - confirmed email verification, may have completed signup
    {
        "lead_id": 25,
        "to": "jimwalkup@gmail.com",
        "name": "Jim",
        "body": """Hi Jim,

Just checking in — we fixed several bugs on the platform since you confirmed your account. The profile editor and dashboard are fully working now.

If you haven't had a chance to complete your profile yet, you can log in anytime at https://www.weddingcounselors.com/professional/signup and add your bio, credentials, and specialties. Couples are already browsing the directory, so a complete profile means you'll start showing up in searches right away.

Sarah, Wedding Counselors Directory"""
    },

    # 6. Jim Brazel - changed email to jim@westmichiganwellnessgroup.com
    {
        "lead_id": 110,
        "to": "jimbwmwg@gmail.com",
        "name": "Jim",
        "body": """Hi Jim,

Following up — you mentioned you'd prefer to use jim@westmichiganwellnessgroup.com. I wanted to let you know the signup is ready whenever you are, and you can register with whichever email you prefer.

We had some bugs when I originally sent the link but everything is fixed and working smoothly now. Takes about 2 minutes.

Here's the link: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 7. Sarah Kenville - "Yes, I would love to be included" Feb 6, got steps Feb 7
    {
        "lead_id": 116,
        "to": "enrichyourrelationship@gmail.com",
        "name": "Sarah",
        "body": """Hi Sarah,

Just circling back — we had a couple technical issues with the signup process when I first sent you the link, which are now fixed. The flow is smooth and self-explanatory now.

Your profile and dashboard go live immediately once you're set up, so couples in Minnesota can start finding you right away.

Here's the link whenever you have 2 minutes: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 8. Dr. Frank MacArthur - "Very interested" Feb 6, got steps Feb 7
    {
        "lead_id": 138,
        "to": "frankmacarthurpsyd@gmail.com",
        "name": "Dr. MacArthur",
        "body": """Hi Dr. MacArthur,

Following up on this — we had some bugs in the signup flow when I originally sent you the link, which have since been resolved. Everything works end-to-end now and the dashboard is live.

Once you complete your profile (takes about 2 minutes), couples searching for premarital counseling in New Jersey will be able to find you and reach out directly.

Here's the link: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 9. Pamela Price-Lerner - "Might be interested if no cost" Feb 6, confirmed free Feb 7
    {
        "lead_id": 177,
        "to": "therapywithpamela@gmail.com",
        "name": "Pam",
        "body": """Hi Pam,

Just following up — to confirm, it's still completely free. No credit card, no hidden fees.

We also fixed some technical issues in the signup process since I last wrote. Everything is working smoothly now — the signup takes about 2 minutes and your dashboard goes live right away.

Here's the link if you'd like to give it a go: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 10. Dr. William Ryan - CRITICAL: tried to sign up, got schema error
    {
        "lead_id": 206,
        "to": "drwilliamryan@gmail.com",
        "name": "Dr. Ryan",
        "body": """Hi Dr. Ryan,

I wanted to follow up on the error you encountered during signup. That bug has been fixed — the schema issue you hit is resolved and the entire signup flow has been updated.

If you'd like to try again, here's the direct link: https://www.weddingcounselors.com/professional/signup

It should work smoothly now. If you run into anything at all, just reply here and I'll take care of it.

Sarah, Wedding Counselors Directory"""
    },

    # 11. Min. April Brown - "I will join today. Excited!" Feb 9 - very recent
    {
        "lead_id": 180,
        "to": "maritalminister@gmail.com",
        "name": "Min. Brown",
        "body": """Hi Min. Brown,

Just wanted to make sure you were able to get signed up — we had a couple bugs on the platform over the past few days that have since been fixed. The flow is self-explanatory now and takes about 2 minutes.

Your profile and dashboard go live immediately, so couples in Virginia can find you right away.

Here's the direct link in case you need it again: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 12. Amanda Augustenborg - "Interested in learning more" Feb 7
    {
        "lead_id": 190,
        "to": "amandaaugustenborg@gmail.com",
        "name": "Amanda",
        "body": """Hi Amanda,

Following up — we've fixed several bugs on the platform since I last wrote. The signup process is straightforward now and takes about 2 minutes. No credit card or fees.

You'll get a dedicated profile page and a dashboard to track views and inquiries from couples in your area.

Here's the link whenever you're ready: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 13. Martha Maurno (Box Elder) - said "Yes!" Feb 7, got steps same day
    {
        "lead_id": 236,
        "to": "boxelderbehavioralhealth@gmail.com",
        "name": "Martha",
        "body": """Hi Martha,

Following up on this — we had some technical issues with the signup when I first sent the link, which are now resolved. The process is smooth now and takes about 2 minutes.

Once your profile is set up, your dashboard goes live immediately and couples can start finding you through the directory.

Here's the link: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 14. Anthony Thomas - "Yes. Let me know what to do" Feb 7, got steps same day
    {
        "lead_id": 241,
        "to": "anthonythomas.lcsw@gmail.com",
        "name": "Anthony",
        "body": """Hi Anthony,

Just circling back — we've resolved some bugs in the signup flow since I last sent you the link. Everything works end-to-end now and the process is self-explanatory.

Your profile and analytics dashboard go live as soon as you complete the 2-minute setup. Couples in North Carolina are already browsing the directory.

Here's the link: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 15. Britney (Sparrow Counseling) - "I'm interested" Feb 8, got steps same day
    {
        "lead_id": 283,
        "to": "sparrowcounselingonline@gmail.com",
        "name": "Britney",
        "body": """Hi Britney,

Following up on this — we fixed a few bugs on the signup page since I sent you the link. Everything is working smoothly now.

The signup takes about 2 minutes and your dashboard goes live immediately so you can see profile views and inquiries from couples in Washington.

Here's the link: https://www.weddingcounselors.com/professional/signup

Sarah, Wedding Counselors Directory"""
    },

    # 16. Jeff Adorador - "What's next?" Feb 9 (today) - got reply today but fresh
    {
        "lead_id": 161,
        "to": "jadoradorlmft@gmail.com",
        "name": "Jeffrey",
        "body": """Hi Jeffrey,

Just a quick note — we resolved some bugs on the platform since I sent you the signup steps earlier. The flow is smooth and self-explanatory now.

Takes about 2 minutes to get your profile live: https://www.weddingcounselors.com/professional/signup

Let me know if you have any questions.

Sarah, Wedding Counselors Directory"""
    },
]


def main():
    print(f"Sending {len(BUMPS)} personalized bump emails...\n")

    for i, bump in enumerate(BUMPS):
        lead_id = bump["lead_id"]
        to_email = bump["to"]
        name = bump["name"]
        body = bump["body"].strip()

        # Get threading info
        in_reply_to, references, subject = get_thread_info(lead_id)

        print(f"[{i+1}/{len(BUMPS)}] Sending to {name} ({to_email})")
        print(f"  Subject: {subject}")
        print(f"  In-Reply-To: {in_reply_to}")
        print(f"  References: {references[:80]}...")

        try:
            message_id = send_threaded_reply(
                to_email=to_email,
                subject=subject,
                body_text=body,
                in_reply_to=in_reply_to,
                references=references,
            )
            print(f"  SENT OK: {message_id}")

            # Record in database
            record_sent(lead_id, message_id, subject, body)
            print(f"  Recorded in DB")

        except Exception as e:
            print(f"  ERROR: {e}")

        # Small delay between sends
        if i < len(BUMPS) - 1:
            time.sleep(3)

        print()

    print("Done!")


if __name__ == "__main__":
    main()
