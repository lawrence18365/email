from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from functools import wraps
from config import Config
from models import db, Lead, Campaign, Sequence, Inbox, SentEmail, Response, CampaignLead, CampaignInbox, SendingSchedule
from sqlalchemy import text
from email_handler import EmailSender, EmailReceiver, EmailPersonalizer
from scheduler import EmailScheduler
from unsubscribe import verify_unsubscribe_token
import csv
from io import StringIO
from datetime import datetime, timedelta

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

# Initialize scheduler
scheduler = EmailScheduler(app, db)


def _set_inbox_schedule(inbox_id: int, start_hour: int, end_hour: int, max_per_hour: int) -> None:
    """Replace an inbox's hourly schedule with a simple time window."""
    SendingSchedule.query.filter_by(inbox_id=inbox_id).delete()

    for hour in range(24):
        if start_hour <= end_hour:
            active = start_hour <= hour < end_hour
        else:
            # Overnight window (e.g., 20 -> 6)
            active = hour >= start_hour or hour < end_hour

        schedule = SendingSchedule(
            inbox_id=inbox_id,
            hour_of_day=hour,
            max_per_hour=max_per_hour,
            active=active
        )
        db.session.add(schedule)

    db.session.commit()


def _set_campaign_rotation_inboxes(campaign: Campaign, inbox_ids: list[int]) -> None:
    """Replace a campaign's rotation inbox pool."""
    CampaignInbox.query.filter_by(campaign_id=campaign.id).delete()
    for inbox_id in inbox_ids:
        db.session.add(CampaignInbox(campaign_id=campaign.id, inbox_id=inbox_id))
    db.session.commit()


def _get_inbox_window(inbox_id: int) -> tuple[int, int]:
    """Return the simple sending window for an inbox."""
    schedules = SendingSchedule.query.filter_by(inbox_id=inbox_id).all()
    if not schedules:
        return Config.DEFAULT_SENDING_HOURS_START, Config.DEFAULT_SENDING_HOURS_END

    active_by_hour = {s.hour_of_day: s.active for s in schedules}
    if not any(active_by_hour.values()):
        return Config.DEFAULT_SENDING_HOURS_START, Config.DEFAULT_SENDING_HOURS_END

    # Find first active hour
    start_hour = None
    for hour in range(24):
        if active_by_hour.get(hour, False):
            start_hour = hour
            break

    if start_hour is None:
        return Config.DEFAULT_SENDING_HOURS_START, Config.DEFAULT_SENDING_HOURS_END

    # Find end hour after the active block
    end_hour = None
    for offset in range(1, 25):
        hour = (start_hour + offset) % 24
        if not active_by_hour.get(hour, False):
            end_hour = hour
            break

    if end_hour is None:
        return Config.DEFAULT_SENDING_HOURS_START, Config.DEFAULT_SENDING_HOURS_END

    return start_hour, end_hour


# Authentication disabled for local development
# To enable, uncomment the code below
#
# def basic_auth_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         auth = request.authorization
#         if not auth or auth.username != Config.BASIC_AUTH_USERNAME or auth.password != Config.BASIC_AUTH_PASSWORD:
#             return ('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
#         return f(*args, **kwargs)
#     return decorated_function
#
# @app.before_request
# def require_auth():
#     if request.endpoint and not request.endpoint.startswith('static'):
#         return basic_auth_required(lambda: None)()


# ============================================================================
# Dashboard Routes
# ============================================================================

@app.route('/unsubscribe/<token>')
def unsubscribe(token):
    """One-click unsubscribe handler."""
    max_age_seconds = Config.UNSUBSCRIBE_TOKEN_MAX_DAYS * 24 * 60 * 60
    data = verify_unsubscribe_token(token, max_age_seconds)
    if not data:
        return render_template(
            'unsubscribe.html',
            success=False,
            message="This unsubscribe link is invalid or expired."
        )

    lead = Lead.query.filter_by(id=data['lead_id'], email=data['email']).first()
    if not lead:
        return render_template(
            'unsubscribe.html',
            success=True,
            message="You're already unsubscribed."
        )

    lead.status = 'not_interested'

    campaign_leads = CampaignLead.query.filter_by(lead_id=lead.id, status='active').all()
    for cl in campaign_leads:
        cl.status = 'completed'

    db.session.commit()

    return render_template(
        'unsubscribe.html',
        success=True,
        email=lead.email
    )

@app.route('/')
def dashboard():
    """Main dashboard"""
    # Stats
    total_leads = Lead.query.count()
    active_campaigns = Campaign.query.filter_by(status='active').count()

    # Emails sent today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    emails_sent_today = SentEmail.query.filter(
        SentEmail.sent_at >= today_start,
        SentEmail.status == 'sent'
    ).count()

    # Recent responses (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_responses = Response.query.filter(
        Response.received_at >= week_ago
    ).order_by(Response.received_at.desc()).limit(10).all()

    # Response stats
    total_responses = Response.query.count()
    meetings_booked = Response.query.filter_by(meeting_booked=True).count()

    # Lead status breakdown
    leads_by_status = db.session.query(
        Lead.status,
        db.func.count(Lead.id)
    ).group_by(Lead.status).all()

    status_counts = {status: count for status, count in leads_by_status}

    return render_template('dashboard.html',
                         total_leads=total_leads,
                         active_campaigns=active_campaigns,
                         emails_sent_today=emails_sent_today,
                         recent_responses=recent_responses,
                         total_responses=total_responses,
                         meetings_booked=meetings_booked,
                         status_counts=status_counts)


@app.route('/deliverability')
def deliverability():
    """Deliverability guardrails dashboard"""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    window_start = now - timedelta(minutes=Config.SPIKE_WINDOW_MINUTES)

    inbox_rows = []
    inboxes = Inbox.query.all()

    for inbox in inboxes:
        sent_last_week = SentEmail.query.filter(
            SentEmail.inbox_id == inbox.id,
            SentEmail.sent_at >= week_ago,
            SentEmail.status == 'sent'
        ).count()

        failed_last_week = SentEmail.query.filter(
            SentEmail.inbox_id == inbox.id,
            SentEmail.sent_at >= week_ago,
            SentEmail.status == 'failed'
        ).count()

        bounced_last_week = SentEmail.query.filter(
            SentEmail.inbox_id == inbox.id,
            SentEmail.sent_at >= week_ago,
            SentEmail.status == 'bounced'
        ).count()

        last_hour = SentEmail.query.filter(
            SentEmail.inbox_id == inbox.id,
            SentEmail.sent_at >= now - timedelta(hours=1),
            SentEmail.status == 'sent'
        ).count()

        sending_start, sending_end = _get_inbox_window(inbox.id)
        inbox_rows.append({
            "inbox": inbox,
            "sent_last_week": sent_last_week,
            "failed_last_week": failed_last_week,
            "bounced_last_week": bounced_last_week,
            "last_hour": last_hour,
            "sending_start": sending_start,
            "sending_end": sending_end
        })

    total_sent = sum(r["sent_last_week"] for r in inbox_rows)
    total_failed = sum(r["failed_last_week"] for r in inbox_rows)
    total_bounced = sum(r["bounced_last_week"] for r in inbox_rows)

    bounce_rate = (total_bounced / total_sent * 100) if total_sent else 0
    failure_rate = (total_failed / total_sent * 100) if total_sent else 0

    recent_sent = SentEmail.query.filter(
        SentEmail.sent_at >= window_start,
        SentEmail.status == 'sent'
    ).count()
    recent_bounced = SentEmail.query.filter(
        SentEmail.sent_at >= window_start,
        SentEmail.status == 'bounced'
    ).count()
    recent_failed = SentEmail.query.filter(
        SentEmail.sent_at >= window_start,
        SentEmail.status == 'failed'
    ).count()

    recent_bounce_rate = (recent_bounced / recent_sent * 100) if recent_sent else 0
    recent_failure_rate = (recent_failed / recent_sent * 100) if recent_sent else 0

    spike = (
        recent_sent > 0 and (
            recent_bounce_rate >= Config.SPIKE_BOUNCE_RATE or
            recent_failure_rate >= Config.SPIKE_FAILURE_RATE
        )
    )

    return render_template(
        'deliverability.html',
        inbox_rows=inbox_rows,
        total_sent=total_sent,
        total_failed=total_failed,
        total_bounced=total_bounced,
        bounce_rate=bounce_rate,
        failure_rate=failure_rate,
        spike=spike,
        recent_sent=recent_sent,
        recent_bounced=recent_bounced,
        recent_failed=recent_failed,
        recent_bounce_rate=recent_bounce_rate,
        recent_failure_rate=recent_failure_rate,
        spike_window_minutes=Config.SPIKE_WINDOW_MINUTES,
        spike_bounce_rate=Config.SPIKE_BOUNCE_RATE,
        spike_failure_rate=Config.SPIKE_FAILURE_RATE
    )


# ============================================================================
# Lead Routes
# ============================================================================

@app.route('/leads')
def leads():
    """List all leads"""
    # Get filter parameters
    status_filter = request.args.get('status', '')
    search_query = request.args.get('q', '')

    query = Lead.query

    if status_filter:
        query = query.filter_by(status=status_filter)

    if search_query:
        query = query.filter(
            db.or_(
                Lead.email.ilike(f'%{search_query}%'),
                Lead.first_name.ilike(f'%{search_query}%'),
                Lead.last_name.ilike(f'%{search_query}%'),
                Lead.company.ilike(f'%{search_query}%')
            )
        )

    leads = query.order_by(Lead.created_at.desc()).all()

    return render_template('leads.html', leads=leads, status_filter=status_filter, search_query=search_query)


@app.route('/leads/add', methods=['GET', 'POST'])
def add_lead():
    """Add a new lead"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        company = request.form.get('company', '').strip()
        website = request.form.get('website', '').strip()
        source = request.form.get('source', 'manual')

        if not email:
            flash('Email is required', 'error')
            return redirect(url_for('add_lead'))

        # Check if lead already exists
        existing = Lead.query.filter_by(email=email).first()
        if existing:
            flash(f'Lead with email {email} already exists', 'error')
            return redirect(url_for('leads'))

        lead = Lead(
            email=email,
            first_name=first_name,
            last_name=last_name,
            company=company,
            website=website,
            source=source
        )

        db.session.add(lead)
        db.session.commit()

        flash(f'Lead {email} added successfully', 'success')
        return redirect(url_for('leads'))

    return render_template('add_lead.html')


@app.route('/leads/<int:lead_id>/edit', methods=['GET', 'POST'])
def edit_lead(lead_id):
    """Edit a lead"""
    lead = Lead.query.get_or_404(lead_id)

    if request.method == 'POST':
        lead.first_name = request.form.get('first_name', '').strip()
        lead.last_name = request.form.get('last_name', '').strip()
        lead.company = request.form.get('company', '').strip()
        lead.website = request.form.get('website', '').strip()
        lead.status = request.form.get('status', 'new')

        db.session.commit()

        flash(f'Lead {lead.email} updated successfully', 'success')
        return redirect(url_for('leads'))

    return render_template('edit_lead.html', lead=lead)


@app.route('/leads/<int:lead_id>/delete', methods=['POST'])
def delete_lead(lead_id):
    """Delete a lead"""
    lead = Lead.query.get_or_404(lead_id)
    email = lead.email

    db.session.delete(lead)
    db.session.commit()

    flash(f'Lead {email} deleted successfully', 'success')
    return redirect(url_for('leads'))


@app.route('/leads/import', methods=['GET', 'POST'])
def import_leads():
    """Import leads from CSV"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'error')
            return redirect(url_for('import_leads'))

        file = request.files['file']

        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('import_leads'))

        if not file.filename.endswith('.csv'):
            flash('File must be a CSV', 'error')
            return redirect(url_for('import_leads'))

        try:
            # Read CSV
            stream = StringIO(file.stream.read().decode('utf-8'))
            csv_reader = csv.DictReader(stream)

            imported = 0
            skipped = 0

            for row in csv_reader:
                email = row.get('email', '').strip()

                if not email:
                    skipped += 1
                    continue

                # Check if exists
                existing = Lead.query.filter_by(email=email).first()
                if existing:
                    skipped += 1
                    continue

                lead = Lead(
                    email=email,
                    first_name=row.get('first_name', '').strip(),
                    last_name=row.get('last_name', '').strip(),
                    company=row.get('company', '').strip(),
                    website=row.get('website', '').strip(),
                    source='csv_import'
                )

                db.session.add(lead)
                imported += 1

            db.session.commit()

            flash(f'Imported {imported} leads, skipped {skipped}', 'success')
            return redirect(url_for('leads'))

        except Exception as e:
            flash(f'Error importing CSV: {str(e)}', 'error')
            return redirect(url_for('import_leads'))

    return render_template('import_leads.html')


# ============================================================================
# Campaign Routes
# ============================================================================

@app.route('/campaigns')
def campaigns():
    """List all campaigns"""
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).all()

    # Get stats for each campaign
    campaign_stats = []
    for campaign in campaigns:
        sent_count = SentEmail.query.filter_by(campaign_id=campaign.id, status='sent').count()
        response_count = db.session.query(Response).join(SentEmail).filter(
            SentEmail.campaign_id == campaign.id
        ).count()

        campaign_stats.append({
            'campaign': campaign,
            'sent': sent_count,
            'responses': response_count
        })

    return render_template('campaigns.html', campaign_stats=campaign_stats)


@app.route('/campaigns/add', methods=['GET', 'POST'])
def add_campaign():
    """Create a new campaign"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        inbox_id = request.form.get('inbox_id')
        rotation_ids = request.form.getlist('rotation_inbox_ids')

        if not name or not inbox_id:
            flash('Name and inbox are required', 'error')
            return redirect(url_for('add_campaign'))

        inbox_id_int = int(inbox_id)
        rotation_ids_int = [int(i) for i in rotation_ids] if rotation_ids else []
        if inbox_id_int not in rotation_ids_int:
            rotation_ids_int.insert(0, inbox_id_int)

        campaign = Campaign(
            name=name,
            inbox_id=inbox_id_int,
            status='draft'
        )

        db.session.add(campaign)
        db.session.commit()

        if rotation_ids_int:
            _set_campaign_rotation_inboxes(campaign, rotation_ids_int)

        flash(f'Campaign "{name}" created', 'success')
        return redirect(url_for('edit_campaign', campaign_id=campaign.id))

    inboxes = Inbox.query.filter_by(active=True).all()
    return render_template('add_campaign.html', inboxes=inboxes, rotation_inbox_ids=[])


@app.route('/campaigns/<int:campaign_id>/edit', methods=['GET', 'POST'])
def edit_campaign(campaign_id):
    """Edit a campaign and its sequences"""
    campaign = Campaign.query.get_or_404(campaign_id)

    if request.method == 'POST':
        campaign.name = request.form.get('name', '').strip()
        campaign.status = request.form.get('status', 'draft')
        rotation_ids = request.form.getlist('rotation_inbox_ids')

        db.session.commit()

        rotation_ids_int = [int(i) for i in rotation_ids] if rotation_ids else []
        if campaign.inbox_id not in rotation_ids_int:
            rotation_ids_int.insert(0, campaign.inbox_id)
        _set_campaign_rotation_inboxes(campaign, rotation_ids_int)

        flash(f'Campaign "{campaign.name}" updated', 'success')
        return redirect(url_for('campaigns'))

    sequences = Sequence.query.filter_by(campaign_id=campaign_id).order_by(Sequence.step_number).all()
    inboxes = Inbox.query.filter_by(active=True).all()
    rotation_inbox_ids = [ci.inbox_id for ci in campaign.rotation_inboxes]
    if not rotation_inbox_ids:
        rotation_inbox_ids = [campaign.inbox_id]

    return render_template(
        'edit_campaign.html',
        campaign=campaign,
        sequences=sequences,
        inboxes=inboxes,
        rotation_inbox_ids=rotation_inbox_ids
    )


@app.route('/campaigns/<int:campaign_id>/sequences/add', methods=['POST'])
def add_sequence(campaign_id):
    """Add a sequence step to a campaign"""
    campaign = Campaign.query.get_or_404(campaign_id)

    step_number = request.form.get('step_number', type=int)
    delay_days = request.form.get('delay_days', type=int, default=0)
    subject = request.form.get('subject', '').strip()
    body = request.form.get('body', '').strip()

    if not subject or not body:
        flash('Subject and body are required', 'error')
        return redirect(url_for('edit_campaign', campaign_id=campaign_id))

    sequence = Sequence(
        campaign_id=campaign_id,
        step_number=step_number,
        delay_days=delay_days,
        subject_template=subject,
        email_template=body
    )

    db.session.add(sequence)
    db.session.commit()

    flash(f'Sequence step {step_number} added', 'success')
    return redirect(url_for('edit_campaign', campaign_id=campaign_id))


@app.route('/campaigns/<int:campaign_id>/sequences/<int:sequence_id>/delete', methods=['POST'])
def delete_sequence(campaign_id, sequence_id):
    """Delete a sequence step"""
    sequence = Sequence.query.get_or_404(sequence_id)

    db.session.delete(sequence)
    db.session.commit()

    flash('Sequence step deleted', 'success')
    return redirect(url_for('edit_campaign', campaign_id=campaign_id))


@app.route('/campaigns/<int:campaign_id>/add-leads', methods=['GET', 'POST'])
def add_leads_to_campaign(campaign_id):
    """Add leads to a campaign"""
    campaign = Campaign.query.get_or_404(campaign_id)

    if request.method == 'POST':
        lead_ids = request.form.getlist('lead_ids')

        added = 0
        for lead_id in lead_ids:
            # Check if already in campaign
            existing = CampaignLead.query.filter_by(
                campaign_id=campaign_id,
                lead_id=int(lead_id)
            ).first()

            if not existing:
                campaign_lead = CampaignLead(
                    campaign_id=campaign_id,
                    lead_id=int(lead_id)
                )
                db.session.add(campaign_lead)
                added += 1

        db.session.commit()

        flash(f'Added {added} leads to campaign', 'success')
        return redirect(url_for('campaigns'))

    # Get leads not already in this campaign
    already_in = db.session.query(CampaignLead.lead_id).filter_by(campaign_id=campaign_id).all()
    already_in_ids = [l[0] for l in already_in]

    available_leads = Lead.query.filter(~Lead.id.in_(already_in_ids)).all() if already_in_ids else Lead.query.all()

    return render_template('add_leads_to_campaign.html', campaign=campaign, leads=available_leads)


@app.route('/campaigns/<int:campaign_id>/delete', methods=['POST'])
def delete_campaign(campaign_id):
    """Delete a campaign"""
    campaign = Campaign.query.get_or_404(campaign_id)
    name = campaign.name

    db.session.delete(campaign)
    db.session.commit()

    flash(f'Campaign "{name}" deleted', 'success')
    return redirect(url_for('campaigns'))


@app.route('/campaigns/pause-all', methods=['POST'])
def pause_all_campaigns():
    """Pause all active campaigns"""
    active = Campaign.query.filter_by(status='active').all()
    for campaign in active:
        campaign.status = 'paused'
    db.session.commit()
    flash(f'Paused {len(active)} active campaign(s)', 'success')
    return redirect(url_for('deliverability'))


@app.route('/campaigns/resume-all', methods=['POST'])
def resume_all_campaigns():
    """Resume all paused campaigns"""
    paused = Campaign.query.filter_by(status='paused').all()
    for campaign in paused:
        campaign.status = 'active'
    db.session.commit()
    flash(f'Resumed {len(paused)} paused campaign(s)', 'success')
    return redirect(url_for('deliverability'))


# ============================================================================
# Inbox Routes
# ============================================================================

@app.route('/inboxes')
def inboxes():
    """List all inboxes"""
    inboxes = Inbox.query.all()
    return render_template('inboxes.html', inboxes=inboxes)


@app.route('/inboxes/add', methods=['GET', 'POST'])
def add_inbox():
    """Add a new inbox"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        smtp_host = request.form.get('smtp_host', '').strip()
        smtp_port = request.form.get('smtp_port', 587, type=int)
        imap_host = request.form.get('imap_host', '').strip()
        imap_port = request.form.get('imap_port', 993, type=int)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        max_per_hour = request.form.get('max_per_hour', 5, type=int)
        sending_start = request.form.get('sending_start', Config.DEFAULT_SENDING_HOURS_START, type=int)
        sending_end = request.form.get('sending_end', Config.DEFAULT_SENDING_HOURS_END, type=int)

        inbox = Inbox(
            name=name,
            email=email,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            imap_host=imap_host,
            imap_port=imap_port,
            username=username,
            password=password,
            max_per_hour=max_per_hour
        )

        db.session.add(inbox)
        db.session.commit()

        _set_inbox_schedule(inbox.id, sending_start, sending_end, max_per_hour)

        flash(f'Inbox {email} added', 'success')
        return redirect(url_for('inboxes'))

    return render_template(
        'add_inbox.html',
        sending_start=Config.DEFAULT_SENDING_HOURS_START,
        sending_end=Config.DEFAULT_SENDING_HOURS_END
    )


@app.route('/inboxes/<int:inbox_id>/edit', methods=['GET', 'POST'])
def edit_inbox(inbox_id):
    """Edit an inbox"""
    inbox = Inbox.query.get_or_404(inbox_id)

    if request.method == 'POST':
        inbox.name = request.form.get('name', '').strip()
        inbox.smtp_host = request.form.get('smtp_host', '').strip()
        inbox.smtp_port = request.form.get('smtp_port', 587, type=int)
        inbox.imap_host = request.form.get('imap_host', '').strip()
        inbox.imap_port = request.form.get('imap_port', 993, type=int)
        inbox.username = request.form.get('username', '').strip()
        inbox.max_per_hour = request.form.get('max_per_hour', 5, type=int)

        # Only update password if provided
        password = request.form.get('password', '').strip()
        if password:
            inbox.password = password

        db.session.commit()

        sending_start = request.form.get('sending_start', Config.DEFAULT_SENDING_HOURS_START, type=int)
        sending_end = request.form.get('sending_end', Config.DEFAULT_SENDING_HOURS_END, type=int)
        _set_inbox_schedule(inbox.id, sending_start, sending_end, inbox.max_per_hour)

        flash(f'Inbox {inbox.email} updated', 'success')
        return redirect(url_for('inboxes'))

    sending_start, sending_end = _get_inbox_window(inbox.id)
    return render_template(
        'edit_inbox.html',
        inbox=inbox,
        sending_start=sending_start,
        sending_end=sending_end
    )


@app.route('/inboxes/<int:inbox_id>/test')
def test_inbox(inbox_id):
    """Test inbox connection"""
    inbox = Inbox.query.get_or_404(inbox_id)

    # Test SMTP
    sender = EmailSender(inbox)
    smtp_success, smtp_message = sender.test_connection()

    # Test IMAP
    receiver = EmailReceiver(inbox)
    imap_success, imap_message = receiver.test_connection()

    return jsonify({
        'smtp': {'success': smtp_success, 'message': smtp_message},
        'imap': {'success': imap_success, 'message': imap_message}
    })


@app.route('/inboxes/<int:inbox_id>/delete', methods=['POST'])
def delete_inbox(inbox_id):
    """Delete an inbox"""
    inbox = Inbox.query.get_or_404(inbox_id)
    email = inbox.email

    db.session.delete(inbox)
    db.session.commit()

    flash(f'Inbox {email} deleted', 'success')
    return redirect(url_for('inboxes'))


# ============================================================================
# Response Routes
# ============================================================================

@app.route('/responses')
def responses():
    """List all responses"""
    responses = Response.query.order_by(Response.received_at.desc()).all()
    return render_template('responses.html', responses=responses)


@app.route('/responses/<int:response_id>/mark-meeting', methods=['POST'])
def mark_meeting_booked(response_id):
    """Mark a response as meeting booked"""
    response = Response.query.get_or_404(response_id)

    response.meeting_booked = True
    response.reviewed = True

    # Update lead status
    lead = response.lead
    lead.status = 'meeting_booked'

    db.session.commit()

    flash('Marked as meeting booked', 'success')
    return redirect(url_for('responses'))


@app.route('/responses/<int:response_id>/mark-not-interested', methods=['POST'])
def mark_not_interested(response_id):
    """Mark a response as not interested"""
    response = Response.query.get_or_404(response_id)

    response.reviewed = True

    # Update lead status
    lead = response.lead
    lead.status = 'not_interested'

    db.session.commit()

    flash('Marked as not interested', 'success')
    return redirect(url_for('responses'))


@app.route('/responses/<int:response_id>/update', methods=['POST'])
def update_response(response_id):
    """Update response notes, assignment, label, and reviewed status"""
    response = Response.query.get_or_404(response_id)

    response.notes = request.form.get('notes', '').strip()
    response.assigned_to = request.form.get('assigned_to', '').strip() or None
    response.label = request.form.get('label', '').strip() or None
    response.reviewed = True if request.form.get('reviewed') == 'on' else response.reviewed

    db.session.commit()

    flash('Response updated', 'success')
    return redirect(url_for('responses'))


# ============================================================================
# Tracking Route
# ============================================================================

@app.route('/tracking')
def tracking():
    """Detailed campaign tracking dashboard"""
    from datetime import datetime, timedelta, UTC

    campaigns = Campaign.query.all()
    tracking_data = []

    for campaign in campaigns:
        sequences = Sequence.query.filter_by(campaign_id=campaign.id).order_by(Sequence.step_number).all()
        campaign_leads = CampaignLead.query.filter_by(campaign_id=campaign.id).all()

        lead_progress = []
        for cl in campaign_leads:
            lead = db.session.get(Lead, cl.lead_id)
            sent_emails = SentEmail.query.filter_by(
                lead_id=lead.id,
                campaign_id=campaign.id
            ).order_by(SentEmail.sequence_id).all()

            steps = []
            sent_step_ids = {se.sequence_id for se in sent_emails}

            for seq in sequences:
                sent_email = next((se for se in sent_emails if se.sequence_id == seq.id), None)
                if sent_email:
                    inbox = db.session.get(Inbox, sent_email.inbox_id)
                    steps.append({
                        'step': seq.step_number,
                        'status': 'sent',
                        'sent_at': sent_email.sent_at,
                        'inbox': inbox.name if inbox else 'Unknown',
                        'email_status': sent_email.status
                    })
                else:
                    # Calculate when this step will be sent
                    if sent_emails:
                        last_sent = sent_emails[-1].sent_at
                        next_send = last_sent + timedelta(days=seq.delay_days)
                        days_until = (next_send - datetime.now(UTC).replace(tzinfo=None)).days
                    else:
                        days_until = seq.delay_days

                    steps.append({
                        'step': seq.step_number,
                        'status': 'pending',
                        'days_until': max(0, days_until),
                        'delay_days': seq.delay_days
                    })

            lead_progress.append({
                'lead': lead,
                'campaign_status': cl.status,
                'steps': steps,
                'total_sent': len(sent_emails),
                'total_steps': len(sequences)
            })

        tracking_data.append({
            'campaign': campaign,
            'sequences': sequences,
            'leads': lead_progress,
            'total_leads': len(campaign_leads),
            'total_sent': SentEmail.query.filter_by(campaign_id=campaign.id).count(),
            'total_responses': Response.query.join(SentEmail).filter(SentEmail.campaign_id == campaign.id).count()
        })

    # Inbox stats
    inboxes = Inbox.query.filter_by(active=True).all()
    inbox_stats = []
    for inbox in inboxes:
        hour_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        sent_last_hour = SentEmail.query.filter(
            SentEmail.inbox_id == inbox.id,
            SentEmail.sent_at >= hour_ago
        ).count()
        inbox_stats.append({
            'inbox': inbox,
            'sent_last_hour': sent_last_hour,
            'capacity': inbox.max_per_hour
        })

    return render_template('tracking.html',
                         tracking_data=tracking_data,
                         inbox_stats=inbox_stats)


# ============================================================================
# Autopilot Routes
# ============================================================================

@app.route('/autopilot')
def autopilot():
    """Autopilot control center"""
    from datetime import datetime, timedelta

    # Stats
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {
        'leads_found_today': Lead.query.filter(
            Lead.created_at >= today_start,
            Lead.source.like('%prospecting%')
        ).count(),
        'replies_sent_today': SentEmail.query.filter(
            SentEmail.sent_at >= today_start
        ).count(),
        'meetings_booked': Response.query.filter_by(meeting_booked=True).count()
    }

    # Pending responses
    pending_responses = Response.query.filter_by(reviewed=False).count()
    recent_responses = Response.query.order_by(Response.received_at.desc()).limit(10).all()

    # Campaigns for dropdown
    campaigns = Campaign.query.filter_by(status='active').all()

    # Recent activity (mock for now - could be real activity log)
    recent_activity = []

    # Scheduler status (mock)
    scheduler_status = {
        'send_emails_last': 'Running',
        'check_responses_last': 'Running',
        'auto_reply_last': 'Running',
        'prospecting_last': 'Running'
    }

    return render_template('autopilot.html',
                         stats=stats,
                         pending_responses=pending_responses,
                         recent_responses=recent_responses,
                         campaigns=campaigns,
                         recent_activity=recent_activity,
                         scheduler_status=scheduler_status,
                         auto_reply_enabled=True)


@app.route('/api/autopilot/find-leads', methods=['POST'])
def api_find_leads():
    """API: Find new leads using AI"""
    from lead_finder import LeadFinderScheduler

    data = request.get_json()

    criteria = {
        'industry': data.get('industry', ''),
        'location': data.get('location', ''),
        'keywords': data.get('keywords', []),
        'job_titles': data.get('job_titles', [])
    }

    limit = data.get('limit', 20)
    auto_add = data.get('auto_add', True)

    try:
        finder = LeadFinderScheduler(app, db)
        result = finder.run_prospecting(criteria, limit, auto_add)

        return jsonify({
            'success': True,
            'found': result['found'],
            'added': result['added'],
            'skipped': result['skipped'],
            'leads': result.get('leads', [])
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/autopilot/process-responses', methods=['POST'])
def api_process_responses():
    """API: Process responses and send AI replies"""
    from ai_responder import AutoReplyScheduler

    try:
        responder = AutoReplyScheduler(app, db)
        replies_sent = responder.process_pending_responses()

        return jsonify({
            'success': True,
            'replies_sent': replies_sent
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/autopilot/enrich-leads', methods=['POST'])
def api_enrich_leads():
    """API: Enrich unenriched leads with company data"""
    from lead_enrichment import enrich_all_unenriched_leads

    data = request.get_json() or {}
    limit = data.get('limit', 10)

    try:
        result = enrich_all_unenriched_leads(app, db, limit=limit)
        return jsonify({
            'success': True,
            'result': result
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/autopilot/enrich-lead/<int:lead_id>', methods=['POST'])
def api_enrich_single_lead(lead_id):
    """API: Enrich a specific lead"""
    from lead_enrichment import enrich_lead_in_db

    try:
        success = enrich_lead_in_db(app, db, lead_id)
        if success:
            lead = db.session.get(Lead, lead_id)
            return jsonify({
                'success': True,
                'lead': {
                    'id': lead.id,
                    'email': lead.email,
                    'company': lead.company,
                    'industry': lead.industry,
                    'company_description': lead.company_description,
                    'personalized_opener': lead.personalized_opener,
                    'enriched': lead.enriched
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Enrichment failed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/autopilot/full', methods=['POST'])
def api_full_autopilot():
    """API: Run full autopilot cycle (now includes enrichment)"""
    from lead_enrichment import enrich_all_unenriched_leads

    results = {
        'success': True,
        'enrichment': None,
        'send_emails': None,
        'check_responses': None
    }

    try:
        # Step 1: Enrich unenriched leads
        try:
            enrichment_result = enrich_all_unenriched_leads(app, db, limit=5)
            results['enrichment'] = enrichment_result
        except Exception as e:
            results['enrichment'] = {'error': str(e)}

        # Step 2: Send scheduled emails
        try:
            scheduler.send_scheduled_emails()
            results['send_emails'] = {'status': 'completed'}
        except Exception as e:
            results['send_emails'] = {'error': str(e)}

        # Step 3: Check for responses
        try:
            response_count = scheduler.check_responses()
            results['check_responses'] = {'new_responses': response_count}
        except Exception as e:
            results['check_responses'] = {'error': str(e)}

        return jsonify(results)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/autopilot/assign-leads', methods=['POST'])
def api_assign_leads():
    """API: Assign new leads to a campaign"""
    data = request.get_json()
    campaign_id = data.get('campaign_id')

    try:
        # Get new leads not in any campaign
        new_leads = Lead.query.filter_by(status='new').all()

        if campaign_id == 'best':
            # Find best performing campaign
            best_campaign = None
            best_rate = 0

            campaigns = Campaign.query.filter_by(status='active').all()
            for campaign in campaigns:
                sent = SentEmail.query.filter_by(campaign_id=campaign.id, status='sent').count()
                responses = db.session.query(Response).join(SentEmail).filter(
                    SentEmail.campaign_id == campaign.id
                ).count()
                rate = (responses / sent * 100) if sent > 0 else 0

                if rate > best_rate or best_campaign is None:
                    best_rate = rate
                    best_campaign = campaign

            campaign = best_campaign
        else:
            campaign = Campaign.query.get(int(campaign_id))

        if not campaign:
            return jsonify({'success': False, 'message': 'No active campaigns found'})

        assigned = 0
        for lead in new_leads:
            existing = CampaignLead.query.filter_by(
                campaign_id=campaign.id,
                lead_id=lead.id
            ).first()

            if not existing:
                cl = CampaignLead(campaign_id=campaign.id, lead_id=lead.id)
                db.session.add(cl)
                assigned += 1

        db.session.commit()

        return jsonify({
            'success': True,
            'assigned': assigned,
            'campaign_name': campaign.name
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/autopilot/toggle-auto-reply', methods=['POST'])
def api_toggle_auto_reply():
    """API: Toggle automatic replies"""
    data = request.get_json()
    enabled = data.get('enabled', True)

    # Store in config or session (for now just return success)
    return jsonify({'success': True, 'enabled': enabled})


# ============================================================================
# Application Startup
# ============================================================================

def create_tables():
    """Create all database tables"""
    with app.app_context():
        db.create_all()
        inboxes = Inbox.query.all()
        for inbox in inboxes:
            has_schedule = SendingSchedule.query.filter_by(inbox_id=inbox.id).first()
            if not has_schedule:
                _set_inbox_schedule(
                    inbox.id,
                    Config.DEFAULT_SENDING_HOURS_START,
                    Config.DEFAULT_SENDING_HOURS_END,
                    inbox.max_per_hour
                )
        _ensure_response_columns()


def _ensure_response_columns() -> None:
    """Add missing columns to responses table for lightweight migrations."""
    columns = db.session.execute(text("PRAGMA table_info(responses)")).fetchall()
    existing = {col[1] for col in columns}

    if "assigned_to" not in existing:
        db.session.execute(text("ALTER TABLE responses ADD COLUMN assigned_to TEXT"))
    if "label" not in existing:
        db.session.execute(text("ALTER TABLE responses ADD COLUMN label TEXT"))
    db.session.commit()


if __name__ == '__main__':
    create_tables()
    scheduler.start()

    try:
        app.run(debug=Config.DEBUG, host='0.0.0.0', port=5001)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
