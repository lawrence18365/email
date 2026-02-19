#!/usr/bin/env python3
"""
Bounce Management CLI Tool

Commands:
    check       - Check for new bounces in all inboxes
    report      - Generate bounce report
    export      - Export bounced emails to CSV
    clean       - Delete old hard bounces (after review period)
    list        - List all bounced emails

Usage:
    python manage_bounces.py check
    python manage_bounces.py report --days 30
    python manage_bounces.py export --file bounces.csv
    python manage_bounces.py clean --days 30 --dry-run
"""

import argparse
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db
from bounce_handler import BounceProcessor, BounceCleaner, check_and_process_bounces


def cmd_check(args):
    """Check for bounces in all inboxes"""
    print("🔍 Checking for bounced emails...")
    
    with app.app_context():
        result = check_and_process_bounces(app, db)
        
        print(f"\n✅ Found {result['bounces_found']} new bounces")
        print(f"\n📊 30-Day Report:")
        report = result['report']
        print(f"   Total bounced: {report['total_bounced']}")
        print(f"   Hard bounces: {report['hard_bounces']}")
        print(f"   Complaints: {report['complaints']}")
        print(f"   Bounce rate: {report['bounce_rate_percent']}%")
        
        if report['recommendations']:
            print("\n⚠️  Recommendations:")
            for rec in report['recommendations']:
                print(f"   • {rec}")


def cmd_report(args):
    """Generate bounce report"""
    print(f"📊 Generating bounce report (last {args.days} days)...")
    
    with app.app_context():
        processor = BounceProcessor(db.session)
        report = processor.generate_bounce_report(days=args.days)
        
        print(f"\n{'='*60}")
        print("BOUNCE REPORT")
        print(f"{'='*60}")
        print(f"Period: Last {report['period_days']} days")
        print(f"Total bounced: {report['total_bounced']}")
        print(f"  • Hard bounces: {report['hard_bounces']}")
        print(f"  • Spam complaints: {report['complaints']}")
        print(f"\nBounce rate: {report['bounce_rate_percent']}%")
        
        if report['recommendations']:
            print("\n⚠️  Recommendations:")
            for rec in report['recommendations']:
                print(f"   • {rec}")
        
        if args.details and report['bounced_emails']:
            print(f"\n📋 Bounced Emails ({len(report['bounced_emails'])} shown):")
            print("-" * 60)
            for item in report['bounced_emails']:
                print(f"   {item['email']}")
                print(f"   Status: {item['status']}")
                print(f"   Date: {item['date']}")
                if item['reason']:
                    print(f"   Reason: {item['reason'][:80]}...")
                print()


def cmd_export(args):
    """Export bounced emails to CSV"""
    print(f"📁 Exporting bounced emails to {args.file}...")
    
    with app.app_context():
        cleaner = BounceCleaner(db.session)
        count = cleaner.export_bounced(args.file)
        
        print(f"✅ Exported {count} bounced emails to {args.file}")
        print(f"\nReview this file before running 'clean' to delete them.")


def cmd_clean(args):
    """Clean/delete old hard bounces"""
    mode = "[DRY RUN - No changes]" if args.dry_run else "[LIVE - Will delete]"
    print(f"🧹 Cleaning hard bounces older than {args.days} days {mode}")
    
    with app.app_context():
        cleaner = BounceCleaner(db.session)
        
        # First show what would be deleted
        to_review = cleaner.get_bounced_for_review(min_age_days=args.days)
        
        if not to_review:
            print("✅ No bounced emails ready for deletion.")
            return
        
        print(f"\nFound {len(to_review)} bounced emails for review:")
        for lead in to_review[:10]:
            print(f"   • {lead.email} ({lead.status}) - Bounced: {lead.updated_at}")
        
        if len(to_review) > 10:
            print(f"   ... and {len(to_review) - 10} more")
        
        if args.dry_run:
            print(f"\n[DRY RUN] Would delete {len(to_review)} emails")
            print("Run without --dry-run to actually delete.")
            return
        
        # Confirm deletion
        if not args.force:
            confirm = input(f"\n⚠️  Delete {len(to_review)} bounced emails permanently? [y/N]: ")
            if confirm.lower() != 'y':
                print("Cancelled.")
                return
        
        count = cleaner.delete_hard_bounces(min_age_days=args.days, dry_run=False)
        print(f"✅ Deleted {count} hard bounced emails")


def cmd_list(args):
    """List all bounced emails"""
    from models import Lead
    
    with app.app_context():
        bounced = Lead.query.filter(
            Lead.status.in_(['bounced', 'complained'])
        ).order_by(Lead.updated_at.desc()).all()
        
        if not bounced:
            print("✅ No bounced emails found.")
            return
        
        print(f"\n📋 Bounced Emails ({len(bounced)} total):")
        print("-" * 80)
        print(f"{'Email':<40} {'Status':<12} {'Date':<20}")
        print("-" * 80)
        
        for lead in bounced:
            date_str = lead.updated_at.strftime('%Y-%m-%d') if lead.updated_at else 'Unknown'
            print(f"{lead.email:<40} {lead.status:<12} {date_str:<20}")
            if args.reason and lead.notes:
                print(f"  └─ {lead.notes[:60]}...")


def main():
    parser = argparse.ArgumentParser(
        description='Manage bounced emails in the CRM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python manage_bounces.py check                    # Check for new bounces
  python manage_bounces.py report --days 7          # 7-day report
  python manage_bounces.py list --reason            # List with reasons
  python manage_bounces.py export --file out.csv    # Export to CSV
  python manage_bounces.py clean --days 30 --dry-run # Preview cleanup
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # check command
    check_parser = subparsers.add_parser('check', help='Check for new bounces')
    
    # report command
    report_parser = subparsers.add_parser('report', help='Generate bounce report')
    report_parser.add_argument('--days', type=int, default=30, help='Days to include (default: 30)')
    report_parser.add_argument('--details', action='store_true', help='Show detailed list')
    
    # export command
    export_parser = subparsers.add_parser('export', help='Export bounced emails to CSV')
    export_parser.add_argument('--file', default='bounced_emails.csv', help='Output file')
    
    # clean command
    clean_parser = subparsers.add_parser('clean', help='Delete old hard bounces')
    clean_parser.add_argument('--days', type=int, default=30, help='Minimum age in days (default: 30)')
    clean_parser.add_argument('--dry-run', action='store_true', help='Preview only')
    clean_parser.add_argument('--force', action='store_true', help='Skip confirmation')
    
    # list command
    list_parser = subparsers.add_parser('list', help='List all bounced emails')
    list_parser.add_argument('--reason', action='store_true', help='Show bounce reasons')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Run command
    commands = {
        'check': cmd_check,
        'report': cmd_report,
        'export': cmd_export,
        'clean': cmd_clean,
        'list': cmd_list,
    }
    
    commands[args.command](args)


if __name__ == '__main__':
    main()
