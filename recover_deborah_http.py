import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time

TURSO_URL = "https://wedding-counselors-lawrence18365.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NzAyMjk5ODksImlkIjoiOWFkNDg4MzMtYjUyMS00MzFkLWJlMGEtMzBiMzJiMWFjYmE2IiwicmlkIjoiODI1MjAwZmUtYWMxMS00MzUxLTkyYzUtOTFkOTc0NjcxZTEwIn0.5-1J9sKxEnoaRJ0dai5vCeVMryOQZVnRuBjueyCr333pvwdsAmKbzHHBb2uwS9rY8zXeF9MA1JYv-zoI3yEnBA"

def query(sql):
    resp = requests.post(
        f"{TURSO_URL}/v2/pipeline",
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "requests": [
                {"type": "execute", "stmt": {"sql": sql}},
                {"type": "close"}
            ]
        },
        timeout=30
    )
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} - {resp.text}")
        return None
    
    data = resp.json()
    result = data['results'][0]
    if 'error' in result:
        print(f"SQL Error: {result['error']}")
        return None
    
    return result['response']['result']

def recover_deborah():
    print("Starting recovery via HTTP API...")
    
    # 1. Find Deborah
    print("Finding Deborah...")
    res = query("SELECT id, email, status, first_name, last_name FROM leads WHERE email = 'dkperrymsw@gmail.com'")
    if not res or not res['rows']:
        print("Error: Deborah not found!")
        return
    
    # helper to unpack row
    cols = [c['name'] for c in res['cols']]
    row = res['rows'][0]
    vals = {cols[i]: (row[i]['value'] if row[i]['type'] != 'null' else None) for i in range(len(cols))}
    
    lead_id = vals['id']
    status = vals['status']
    print(f"Found Deborah (ID: {lead_id}). Current status: {status}")
    
    # 2. Update Status
    if status != 'active':
        print(f"Updating status from {status} to active...")
        query(f"UPDATE leads SET status = 'active' WHERE id = {lead_id}")
        query(f"INSERT INTO responses (lead_id, subject, body, received_at, reviewed, notified, notes) VALUES ({lead_id}, 'Manual Recovery', 'Reset status to active', datetime('now'), 1, 1, 'Manual recovery by manager')")
        print("✅ Status updated to active.")
    else:
        print("Status is already active.")

    # 3. Get Inbox Credentials
    print("Fetching inbox credentials...")
    
    # Inspect schema
    print("Inspecting inboxes schema...")
    schema_res = query("PRAGMA table_info(inboxes)")
    if schema_res and 'rows' in schema_res:
        columns = [row[1]['value'] for row in schema_res['rows']]
        print(f"Columns in inboxes: {columns}")
    
    # Select all columns to be safe
    res = query("SELECT * FROM inboxes WHERE email LIKE '%weddingcounselors.com%' LIMIT 1")
    if not res or not res['rows']:
        # Fallback
        res = query("SELECT * FROM inboxes LIMIT 1")
    
    if not res or not res['rows']:
        print("Error: No inbox found!")
        return

    cols = [c['name'] for c in res['cols']]
    row = res['rows'][0]
    inbox = {cols[i]: (row[i]['value'] if row[i]['type'] != 'null' else None) for i in range(len(cols))}
    
    print(f"Using inbox: {inbox.get('email')}")
    # Inspect keys to find smtp creds
    print(f"Inbox keys: {list(inbox.keys())}")
    
    # Try to map common names
    smtp_host = inbox.get('smtp_host') or inbox.get('host')
    smtp_port = inbox.get('smtp_port') or inbox.get('port')
    smtp_user = inbox.get('smtp_user') or inbox.get('username') or inbox.get('user') or inbox.get('email')
    smtp_password = inbox.get('smtp_password') or inbox.get('password') or inbox.get('pass')
    
    if not smtp_host or not smtp_password:
        print("Error: Could not find SMTP credentials in inbox row.")
        return

    # 4. Send Email
    sender_email = inbox.get('email')
    password = smtp_password
    
    msg = MIMEMultipart()
    msg['From'] = f"Sarah, Wedding Counselors Directory <{sender_email}>"
    msg['To'] = vals['email']
    msg['Subject'] = "Re: Your first week on Wedding Counselors"
    
    body = """Hi Deborah,

I owe you a real apology. Two things went wrong on our end, and I want to be completely transparent:

1. **The profile-saving issue was a bug on our side** — not anything you were doing wrong. When you saved your bio, our system showed a success message, but the data wasn't actually being written to the database. We found and fixed the bug this morning. Your profile will save correctly now.

2. **You should never have been unsubscribed.** Our automated system misread your email asking for help and incorrectly processed it as an unsubscribe request. That was a mistake, and I'm sorry for the frustration. You are fully re-subscribed and active.

Your founding member status is safe — nothing has changed with your account.

If you'd like, I'm happy to walk you through updating your profile over a quick call, or you can log in and try again at your dashboard: https://www.weddingcounselors.com/professional/dashboard

Either way, I'll personally make sure everything saves correctly.

Thank you for your patience, and again — I'm sorry for the trouble.

Sarah
Wedding Counselors Directory"""

    html = f"""<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto;">
        <p>{body.replace(chr(10), '<br>')}</p>
        <p style="color: #666; font-size: 12px; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px;">
            Wedding Counselors Directory<br>
            <a href="https://www.weddingcounselors.com" style="color: #666; text-decoration: none;">www.weddingcounselors.com</a>
        </p>
    </div>
</body>
</html>"""

    msg.attach(MIMEText(body, 'plain'))
    msg.attach(MIMEText(html, 'html'))
    
    try:
        print(f"Connecting to SMTP {smtp_host}:{smtp_port}...")
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        server.login(smtp_user, password)
        text = msg.as_string()
        server.sendmail(sender_email, vals['email'], text)
        server.quit()
        print("✅ Email sent successfully!")
        
        # Log to sent_emails
        print("Logging to database...")
        # Escape single quotes in body for SQL
        safe_body = body.replace("'", "''")
        safe_subject = msg['Subject'].replace("'", "''")
        message_id = f"manual-recovery-{int(time.time())}"
        
        # Use simple INSERT for sent_emails. Assuming inbox_id is available as inbox['id']
        inbox_id = inbox.get('id')
        if not inbox_id and 'id' in inbox: inbox_id = inbox['id']
        
        # We need to make sure we have inbox_id. 
        # If columns inspection failed earlier but we have loose 'id' key... 
        # The earlier extraction: inbox = {cols[i]: ...}
        # So inbox['id'] should exist if column 'id' exists.
        
        if not inbox_id:
             print("Warning: Inbox ID missing, skipping log.")
        else:
            sql = f"""
                INSERT INTO sent_emails (lead_id, inbox_id, subject, body, status, sent_at, message_id) 
                VALUES ({lead_id}, {inbox_id}, '{safe_subject}', '{safe_body}', 'sent', datetime('now'), '{message_id}')
            """
            # campaign_id, sequence_id might be required or have constraints. 
            # If schema differs, this might fail. But sending is the priority.
            
            try:
                query(sql)
                print("✅ Email logged.")
            except:
                print("Warning: Failed to log email to DB (schema mismatch?), but email was SENT.")
        
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

if __name__ == "__main__":
    recover_deborah()
