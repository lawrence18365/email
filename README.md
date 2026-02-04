# RateTapMX CRM - Automated Email Follow-up System

A lightweight Python-based CRM system with automated email follow-up sequences for managing leads and booking meetings.

## Features

- **Lead Management**: Add, edit, import leads from CSV
- **Campaign Builder**: Create multi-step email sequences with customizable delays
- **Email Automation**: Automated sending with rate limiting and personalization
- **Response Tracking**: Automatically detect and process email replies
- **Multiple Inboxes**: Support for up to 3 email inboxes with round-robin sending
- **Rate Limiting**: Configurable sending limits to avoid spam filters
- **Web Interface**: Clean Bootstrap 5 UI for managing all aspects of the CRM
- **🤖 AI Agent (NEW)**: Autonomous AI assistant for managing CRM via natural language

## Two Ways to Use the CRM

### 1. Web Interface (Traditional)
Point-and-click interface for manual management:
- Visit `http://localhost:5000` in your browser
- Manually add leads, create campaigns, view responses
- Full visual control over all operations

### 2. AI Agent (Autonomous) ⭐ RECOMMENDED
Natural language AI that manages everything for you:
- Chat naturally: "Import these leads and start a campaign"
- Fully autonomous: Runs in background, optimizes automatically
- Smart decisions: Pauses bad campaigns, identifies opportunities
- See [AGENT_README.md](AGENT_README.md) for full documentation

```bash
# Interactive chat mode
python crm_agent.py

# Autonomous mode (set and forget)
python autonomous_agent.py --once
```

## Technology Stack

- **Backend**: Python 3.10+ with Flask
- **Database**: SQLite (no separate server needed)
- **Email**: Built-in SMTP/IMAP support
- **Scheduling**: APScheduler for background tasks
- **Frontend**: Bootstrap 5 with responsive design

## Installation

1. **Clone or navigate to the project directory**

2. **Create a virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Initialize the database**
   ```bash
   # Basic initialization
   python init_db.py

   # Or with sample data for testing
   python init_db.py --sample
   ```

## Configuration

Edit `.env` file to configure:

- **SECRET_KEY**: Flask secret key for session security
- **AUTH_USERNAME/PASSWORD**: Web interface login credentials
- **MAX_EMAILS_PER_HOUR**: Default rate limit (recommended: 5)
- **SENDING_HOURS_START/END**: Active sending window (e.g., 9 AM - 5 PM)
- **TIMEZONE**: Your timezone (e.g., America/Mexico_City)

## Usage

### Starting the Application

```bash
python app.py
```

The application will be available at `http://localhost:5000`

Default login credentials:
- Username: `admin`
- Password: `changeme`

### Setting Up Email Inboxes

1. Navigate to **Inboxes** in the web interface
2. Click **Add Inbox**
3. Enter SMTP and IMAP settings for your email provider
4. For Gmail:
   - SMTP: smtp.gmail.com:587
   - IMAP: imap.gmail.com:993
   - Use an App Password (not your regular password)
5. Test the connection before saving

### Creating a Campaign

1. Navigate to **Campaigns**
2. Click **New Campaign**
3. Name your campaign and select an inbox
4. Add sequence steps:
   - Step 1: Immediate email (delay = 0 days)
   - Step 2: Follow-up (delay = 3 days)
   - Step 3: Final follow-up (delay = 7 days)
5. Use personalization variables in templates:
   - `{firstName}`, `{lastName}`, `{fullName}`
   - `{email}`, `{company}`, `{website}`
6. Add leads to the campaign
7. Set campaign status to **Active**

### Managing Leads

- **Add manually**: Leads > Add Lead
- **Import CSV**: Leads > Import CSV
  - Required column: `email`
  - Optional columns: `first_name`, `last_name`, `company`, `website`

### Viewing Responses

- Navigate to **Responses** to see all replies
- Mark responses as:
  - **Meeting Booked**: Successful conversion
  - **Not Interested**: Remove from future sequences
- When a lead responds, they are automatically removed from active sequences

## Background Automation

The system runs background jobs automatically:

- **Send scheduled emails**: Every hour (checks if emails are due)
- **Check for responses**: Every 10 minutes (polls IMAP inboxes)
- **Daily cleanup**: 2 AM (for maintenance tasks)

## Rate Limiting & Best Practices

The system includes built-in protections:

- Maximum 5 emails/hour per inbox (configurable)
- Sending only during business hours (9 AM - 5 PM)
- Automatic response detection stops further emails
- Round-robin distribution across multiple inboxes

### Recommended Warmup Schedule

- Week 1: 10 emails/day total
- Week 2: 20 emails/day total
- Week 3: 30 emails/day total
- Week 4+: 50-75 emails/day total

## Project Structure

```
crm/
├── app.py                  # Flask application and routes
├── models.py              # Database models
├── config.py              # Configuration
├── email_handler.py       # SMTP/IMAP operations
├── scheduler.py           # Background automation
├── init_db.py            # Database initialization
├── requirements.txt       # Python dependencies
├── templates/            # HTML templates
│   ├── base.html
│   ├── dashboard.html
│   ├── leads.html
│   ├── campaigns.html
│   ├── inboxes.html
│   └── responses.html
└── static/               # CSS, JS (if needed)
```

## Database Schema

- **leads**: Contact information and status
- **inboxes**: Email account configurations
- **campaigns**: Email campaign definitions
- **sequences**: Multi-step email templates
- **campaign_leads**: Junction table for leads in campaigns
- **sent_emails**: Record of all sent emails
- **responses**: Received replies from leads

## Security

- Basic HTTP authentication on all routes
- Store email passwords securely (use environment variables)
- Never commit `.env` file to version control
- Use app-specific passwords for Gmail accounts
- HTTPS recommended for production deployment

## Deployment

### Local Development
```bash
python app.py
```

### Production (Linux VPS)

1. Install dependencies on server
2. Set up systemd service to run app.py
3. Use nginx as reverse proxy
4. Enable HTTPS with Let's Encrypt
5. Set up daily SQLite backups

Example systemd service (`/etc/systemd/system/crm.service`):

```ini
[Unit]
Description=RateTapMX CRM
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/crm
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## AI Agent Setup (Autonomous Management)

The AI Agent allows you to manage your CRM through natural language and autonomous operation.

### Quick Start

1. **Get Anthropic API Key**
   - Visit [console.anthropic.com](https://console.anthropic.com/)
   - Create an API key
   - Add to `.env`: `ANTHROPIC_API_KEY=your-key-here`

2. **Run Interactive Mode**
   ```bash
   python crm_agent.py
   ```

3. **Try Some Commands**
   ```
   You: Show me dashboard stats
   You: Import leads from sample_leads.csv
   You: Create a sales campaign with 3 steps
   You: Which campaigns are performing best?
   ```

4. **Enable Autonomous Mode** (Optional)
   ```bash
   # Run once
   python autonomous_agent.py --once

   # Set up hourly automatic runs
   ./setup_cron.sh
   ```

### What the AI Agent Can Do

- **Natural Language Control**: "Add these 10 leads to my best campaign"
- **Autonomous Optimization**: Pauses underperforming campaigns automatically
- **Intelligent Analysis**: "Why is campaign 2 performing better than campaign 1?"
- **Bulk Operations**: "Import CSV, categorize leads, and distribute to campaigns"
- **Meeting Detection**: Automatically identifies responses indicating meeting interest
- **Performance Reports**: "Give me a weekly summary"

### Agent vs Web Interface

| Feature | Web Interface | AI Agent |
|---------|--------------|----------|
| Add single lead | ✅ Manual | ✅ Natural language |
| Import CSV | ✅ Upload form | ✅ "Import from file.csv" |
| Create campaign | ✅ Multi-step form | ✅ "Create 3-step campaign" |
| View stats | ✅ Dashboard page | ✅ "Show me stats" |
| Analyze performance | ❌ Manual review | ✅ Automatic insights |
| Optimize campaigns | ❌ Manual | ✅ Autonomous |
| Complex workflows | ❌ Multiple steps | ✅ Single command |
| Run unattended | ❌ No | ✅ Yes (autonomous mode) |

**Recommendation**: Use AI Agent for daily management, Web Interface for detailed review.

For complete AI Agent documentation, see **[AGENT_README.md](AGENT_README.md)**

## Troubleshooting

### Emails not sending
- Check inbox connection (test in Inboxes page)
- Verify rate limits haven't been reached
- Check sending hours configuration
- Review logs for SMTP errors

### Responses not detected
- Verify IMAP settings are correct
- Check that inbox is actively polling (every 10 minutes)
- Ensure Message-ID tracking is working

### Authentication errors
- For Gmail, use App Passwords (not regular password)
- Enable "Less secure app access" if needed
- Check 2FA settings

## Support

For issues or questions:
- Check the logs in the console where app.py is running
- Review inbox connection test results
- Verify database tables were created correctly

## License

This project is proprietary software for RateTapMX.

## Version

Version 2.0.0 - AI Agent Release
- Added autonomous AI agent for natural language control
- Interactive chat mode for CRM management
- Background autonomous optimization
- Smart campaign analysis and decision-making
