#!/usr/bin/env python3
"""
Bounce Management CLI Tool - Turso Direct Version
Uses Turso HTTP API directly instead of SQLAlchemy
"""

import argparse
import sys
import os
import re
import requests
from datetime import datetime, timedelta

TURSO_URL = "https://wedding-counselors-lawrence18365.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NzAyMjk5ODksImlkIjoiOWFkNDg4MzMtYjUyMS00MzFkLWJlMGEtMzBiMzJiMWFjYmE2IiwicmlkIjoiODI1MjAwZmUtYWMxMS00MzUxLTkyYzUtOTFkOTc0NjcxZTEwIn0.5-1J9sKxEnoaRJ0dai5vCeVMryOQZVnRuBjueyCr333pvwdsAmKbzHHBb2uwS9rY8zXeF9MA1JYv-zoI3yEnBA"


def turso_query(sql):
    """Execute a query against Turso"""
    resp = requests.post(
        f"{TURSO_URL}/v2/pipeline",
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
        json={"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]},
        timeout=30
    )
    if resp.status_code == 200:
        data = resp.json()
        result = data['results'][0]
        if 'error' not in result:
            return result['response']['result']
    return None


def get_bounced_leads():
    """Get all bounced leads"""
    result = turso_query("""
        SELECT id, email, first_name, last_name, status, updated_at 
        FROM leads 
        WHERE status = 'bounced' OR status = 'complained'
        ORDER BY updated_at DESC
    """)
    
    leads = []
    if result and 'rows' in result:
        cols = [c['name'] for c in result['cols']]
        for row in result['rows']:
            vals = {cols[i]: (row[i]['value'] if row[i]['type'] != 'null' else None) for i in range(len(cols))}
            leads.append(vals)
    return leads


def get_bounce_stats(days=30):
    """Get bounce statistics"""
    since_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Total bounced
    result = turso_query(f"""
        SELECT COUNT(*) as count FROM leads 
        WHERE (status = 'bounced' OR status = 'complained')
        AND updated_at >= '{since_date}'
    """)
    total_bounced = int(result['rows'][0][0]['value']) if result else 0
    
    # Hard bounces
    result = turso_query(f"""
        SELECT COUNT(*) as count FROM leads 
        WHERE status = 'bounced'
        AND updated_at >= '{since_date}'
    """)
    hard_bounces = int(result['rows'][0][0]['value']) if result else 0
    
    # Complaints
    result = turso_query(f"""
        SELECT COUNT(*) as count FROM leads 
        WHERE status = 'complained'
        AND updated_at >= '{since_date}'
    """)
    complaints = int(result['rows'][0][0]['value']) if result else 0
    
    # Total sent in period (for rate calculation)
    result = turso_query(f"""
        SELECT COUNT(*) as count FROM sent_emails 
        WHERE sent_at >= '{since_date}'
    """)
    total_sent = int(result['rows'][0][0]['value']) if result else 1
    
    bounce_rate = round((total_bounced / total_sent) * 100, 2) if total_sent > 0 else 0
    
    return {
        'total_bounced': total_bounced,
        'hard_bounces': hard_bounces,
        'complaints': complaints,
        'bounce_rate': bounce_rate,
        'total_sent': total_sent
    }


def check_spam_folders():
    """Check IMAP spam/junk folders for bounces"""
    import imaplib
    import email
    
    # Get inbox credentials
    result = turso_query("SELECT email, username, password, imap_host, imap_port FROM inboxes WHERE active = 1")
    
    if not result or 'rows' not in result:
        print("No inboxes found")
        return []
    
    cols = [c['name'] for c in result['cols']]
    bounces_found = []
    
    for row in result['rows']:
        inbox = {cols[i]: (row[i]['value'] if row[i]['type'] != 'null' else None) for i in range(len(cols))}
        
        try:
            print(f"Checking {inbox['email']}...")
            mail = imaplib.IMAP4_SSL(inbox['imap_host'], int(inbox['imap_port']), timeout=30)
            mail.login(inbox['username'], inbox['password'])
            
            # Check Spam/Junk folders
            for folder in ['Spam', 'Junk', 'Quarantine', 'INBOX.Spam']:
                try:
                    status, _ = mail.select(folder)
                    if status != 'OK':
                        continue
                    
                    # Search for recent messages (last 7 days)
                    since_date = (datetime.utcnow() - timedelta(days=7)).strftime('%d-%b-%Y')
                    status, messages = mail.search(None, f'SINCE {since_date}')
                    
                    if status != 'OK':
                        continue
                    
                    msg_ids = messages[0].split()
                    
                    for msg_id in msg_ids:
                        try:
                            status, msg_data = mail.fetch(msg_id, '(RFC822)')
                            if status != 'OK':
                                continue
                            
                            email_msg = email.message_from_bytes(msg_data[0][1])
                            from_addr = email_msg.get('From', '').lower()
                            subject = email_msg.get('Subject', '').lower()
                            
                            # Check if bounce
                            bounce_indicators = ['mailer-daemon', 'postmaster', 'bounce', 'delivery failure', 'undeliverable']
                            if any(ind in from_addr or ind in subject for ind in bounce_indicators):
                                # Extract body
                                body = ""
                                if email_msg.is_multipart():
                                    for part in email_msg.walk():
                                        if part.get_content_type() == 'text/plain':
                                            try:
                                                body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                                break
                                            except:
                                                pass
                                else:
                                    try:
                                        body = email_msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                                    except:
                                        pass
                                
                                # Try to find bounced email in body
                                email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
                                found_emails = re.findall(email_pattern, body)
                                
                                for found_email in found_emails:
                                    found_email = found_email.lower()
                                    if 'mailer-daemon' not in found_email and 'postmaster' not in found_email:
                                        # Check if this email exists in leads
                                        check = turso_query(f"SELECT id, email FROM leads WHERE email = '{found_email}'")
                                        if check and check.get('rows'):
                                            bounces_found.append({
                                                'email': found_email,
                                                'from': from_addr,
                                                'subject': subject,
                                                'folder': folder,
                                                'inbox': inbox['email']
                                            })
                                            break
                                
                        except Exception as e:
                            continue
                            
                except Exception as e:
                    continue
            
            mail.logout()
            
        except Exception as e:
            print(f"Error checking {inbox['email']}: {e}")
    
    return bounces_found


def mark_as_bounced(email, bounce_type='bounced', reason=''):
    """Mark a lead as bounced"""
    # Escape single quotes
    safe_reason = reason.replace("'", "''") if reason else 'Bounce detected'
    
    # Update lead status
    sql = f"""
        UPDATE leads 
        SET status = '{bounce_type}', 
            notes = '{safe_reason}',
            updated_at = datetime('now')
        WHERE email = '{email}'
    """
    
    result = turso_query(sql)
    
    # Also stop any active campaigns for this lead
    lead_result = turso_query(f"SELECT id FROM leads WHERE email = '{email}'")
    if lead_result and lead_result.get('rows'):
        lead_id = lead_result['rows'][0][0]['value']
        turso_query(f"""
            UPDATE campaign_leads 
            SET status = 'stopped' 
            WHERE lead_id = {lead_id} AND status = 'active'
        """)
    
    return True


def export_bounces(filename):
    """Export bounced emails to CSV"""
    bounced = get_bounced_leads()
    
    with open(filename, 'w') as f:
        f.write('Email,First Name,Last Name,Status,Bounced Date\n')
        for lead in bounced:
            f.write(f"{lead['email']},{lead.get('first_name','')},{lead.get('last_name','')},{lead['status']},{lead.get('updated_at','')}\n")
    
    return len(bounced)


def cmd_check(args):
    """Check for bounces"""
    print("🔍 Checking for bounced emails...")
    print()
    
    # Get current stats
    stats = get_bounce_stats(days=30)
    
    print(f"📊 Current Stats (30 days):")
    print(f"   Total bounced: {stats['total_bounced']}")
    print(f"   Hard bounces: {stats['hard_bounces']}")
    print(f"   Complaints: {stats['complaints']}")
    print(f"   Bounce rate: {stats['bounce_rate']}%")
    print()
    
    # Check spam folders
    print("📧 Checking spam/junk folders...")
    bounces = check_spam_folders()
    
    if bounces:
        print(f"\n⚠️  Found {len(bounces)} potential bounces:")
        for b in bounces:
            print(f"   • {b['email']} (in {b['folder']} folder)")
            # Mark them
            mark_as_bounced(b['email'], 'bounced', f"Detected in {b['folder']} folder")
        print(f"\n✅ Marked {len(bounces)} emails as bounced")
    else:
        print("   No new bounces found in spam folders")
    
    # Show all bounced
    print("\n📋 All Bounced Emails:")
    bounced = get_bounced_leads()
    if bounced:
        for lead in bounced:
            print(f"   • {lead['email']} ({lead['status']})")
    else:
        print("   No bounced emails in database")


def cmd_list(args):
    """List all bounced emails"""
    bounced = get_bounced_leads()
    
    if not bounced:
        print("✅ No bounced emails found.")
        return
    
    print(f"\n📋 Bounced Emails ({len(bounced)} total):")
    print("-" * 80)
    print(f"{'Email':<40} {'Status':<12} {'Date':<20}")
    print("-" * 80)
    
    for lead in bounced:
        date_str = lead.get('updated_at', 'Unknown')[:10] if lead.get('updated_at') else 'Unknown'
        print(f"{lead['email']:<40} {lead['status']:<12} {date_str:<20}")
        
        # Note: notes column not available in Turso schema


def cmd_report(args):
    """Generate bounce report"""
    stats = get_bounce_stats(days=args.days)
    
    print(f"\n{'='*60}")
    print("BOUNCE REPORT")
    print(f"{'='*60}")
    print(f"Period: Last {args.days} days")
    print(f"Total sent: {stats['total_sent']}")
    print(f"Total bounced: {stats['total_bounced']}")
    print(f"  • Hard bounces: {stats['hard_bounces']}")
    print(f"  • Complaints: {stats['complaints']}")
    print(f"\nBounce rate: {stats['bounce_rate']}%")
    
    if stats['bounce_rate'] > 5:
        print("\n⚠️  WARNING: Bounce rate is high (>5%). Review email list quality.")
    elif stats['bounce_rate'] > 2:
        print("\n⚠️  Bounce rate is elevated (>2%). Monitor closely.")
    else:
        print("\n✅ Bounce rate is healthy (<2%)")
    
    if args.details:
        bounced = get_bounced_leads()
        if bounced:
            print(f"\n📋 Recent Bounces:")
            for lead in bounced[:20]:
                print(f"   • {lead['email']} ({lead['status']})")


def cmd_export(args):
    """Export to CSV"""
    count = export_bounces(args.file)
    print(f"✅ Exported {count} bounced emails to {args.file}")


def cmd_clean(args):
    """Clean old bounces"""
    cutoff = (datetime.utcnow() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    
    # Find old bounces
    result = turso_query(f"""
        SELECT id, email FROM leads 
        WHERE status = 'bounced' 
        AND updated_at < '{cutoff}'
    """)
    
    to_delete = []
    if result and result.get('rows'):
        cols = [c['name'] for c in result['cols']]
        for row in result['rows']:
            vals = {cols[i]: (row[i]['value'] if row[i]['type'] != 'null' else None) for i in range(len(cols))}
            to_delete.append(vals)
    
    if not to_delete:
        print("✅ No old bounces to clean up.")
        return
    
    print(f"Found {len(to_delete)} bounced emails older than {args.days} days:")
    for item in to_delete[:10]:
        print(f"   • {item['email']}")
    if len(to_delete) > 10:
        print(f"   ... and {len(to_delete) - 10} more")
    
    if args.dry_run:
        print(f"\n[DRY RUN] Would delete {len(to_delete)} emails")
        return
    
    if not args.force:
        confirm = input(f"\n⚠️  Permanently delete {len(to_delete)} bounced emails? [y/N]: ")
        if confirm.lower() != 'y':
            print("Cancelled.")
            return
    
    # Delete them
    deleted = 0
    for item in to_delete:
        turso_query(f"DELETE FROM leads WHERE id = {item['id']}")
        deleted += 1
    
    print(f"✅ Deleted {deleted} bounced emails")


def main():
    parser = argparse.ArgumentParser(
        description='Manage bounced emails (Turso Direct)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python manage_bounces_turso.py check
  python manage_bounces_turso.py list --reason
  python manage_bounces_turso.py report --days 7
  python manage_bounces_turso.py export --file bounces.csv
  python manage_bounces_turso.py clean --days 30 --dry-run
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    subparsers.add_parser('check', help='Check for bounces')
    
    list_parser = subparsers.add_parser('list', help='List bounced emails')
    list_parser.add_argument('--reason', action='store_true', help='Show reasons')
    
    report_parser = subparsers.add_parser('report', help='Generate report')
    report_parser.add_argument('--days', type=int, default=30)
    report_parser.add_argument('--details', action='store_true')
    
    export_parser = subparsers.add_parser('export', help='Export to CSV')
    export_parser.add_argument('--file', default='bounced_emails.csv')
    
    clean_parser = subparsers.add_parser('clean', help='Clean old bounces')
    clean_parser.add_argument('--days', type=int, default=30)
    clean_parser.add_argument('--dry-run', action='store_true')
    clean_parser.add_argument('--force', action='store_true')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    commands = {
        'check': cmd_check,
        'list': cmd_list,
        'report': cmd_report,
        'export': cmd_export,
        'clean': cmd_clean,
    }
    
    commands[args.command](args)


if __name__ == '__main__':
    main()
