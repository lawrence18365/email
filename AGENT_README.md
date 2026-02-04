# AI CRM Agent Documentation

Your autonomous AI assistant for managing the RateTapMX CRM through natural language.

## Overview

The AI CRM Agent provides three ways to interact with your CRM:

1. **Interactive Chat Mode** - Natural language conversation
2. **Command Mode** - Execute single commands
3. **Autonomous Mode** - Fully automated CRM management

## Setup

### 1. Get Your Anthropic API Key

Visit [console.anthropic.com](https://console.anthropic.com/) and create an API key.

### 2. Configure Environment

Add to your `.env` file:
```bash
ANTHROPIC_API_KEY=your-api-key-here
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Interactive Chat Mode (Recommended)

Start a natural conversation with the AI agent:

```bash
python crm_agent.py
```

**Example conversation:**
```
You: Show me the dashboard stats

Agent: Here's your current CRM status:
- Total leads: 145
- Active campaigns: 3
- Emails sent today: 47
- Meetings booked: 8

You: Which campaign is performing best?

Agent: Campaign "Q1 Sales Outreach" has the best performance:
- Response rate: 18.5%
- Meetings booked: 12
- Still actively sending

Would you like me to analyze what makes it successful?

You: Yes, and create a similar campaign

Agent: Analyzing campaign... I'll create a new campaign using the same
approach. [Creates campaign automatically]
Done! Created "Q1 Sales Outreach - Clone" with 3-step sequence...
```

### Command Mode

Execute single commands:

```bash
python crm_agent.py --command "Import leads from new_leads.csv and add them to campaign 1"
```

### Autonomous Mode

Let the AI manage everything:

```bash
# Run once (good for cron jobs)
python autonomous_agent.py --once

# Run continuously every hour
python autonomous_agent.py --interval 3600

# Set up automatic hourly runs
./setup_cron.sh
```

## What the Agent Can Do

### Lead Management

**Add leads manually:**
```
"Add a lead: john@example.com, John Doe, Acme Corp, https://acme.com"
```

**Import from CSV:**
```
"Import leads from sales_leads.csv"
"Import the CSV file and add all leads to campaign 2"
```

**Manage lead status:**
```
"Show me all new leads"
"Update lead 25 status to contacted"
"Find leads that haven't been contacted yet"
```

### Campaign Management

**Create campaigns:**
```
"Create a 3-step email campaign for new leads using inbox 1"

"Build a sales campaign with these steps:
- Day 0: Introduction
- Day 3: Case study follow-up
- Day 7: Final offer"
```

**Manage campaigns:**
```
"Activate campaign 3"
"Pause campaign 1 - response rate is too low"
"Show me all active campaigns"
"Add leads 10-20 to campaign 2"
```

**Optimize campaigns:**
```
"Analyze all campaigns and pause underperforming ones"
"Which campaigns should I focus on?"
"Suggest improvements for campaign 1"
```

### Response Management

**Review responses:**
```
"Show me new responses from this week"
"Are there any responses indicating interest in meetings?"
"Show responses from campaign 2"
```

**Book meetings:**
```
"Mark response 5 as meeting booked"
"Find responses that mention scheduling or meetings"
```

### Analytics & Insights

**Dashboard:**
```
"Give me a dashboard summary"
"What's the overall performance?"
"Any alerts or issues I should know about?"
```

**Campaign analysis:**
```
"Analyze campaign 1 performance"
"Compare all campaigns"
"What's my best performing campaign and why?"
```

**Trends:**
```
"What trends do you see in the responses?"
"Which industries are responding best?"
"How has performance changed over the last week?"
```

### Complex Multi-Step Tasks

The agent can handle complex workflows:

```
"Import new leads, analyze which campaign they'd fit best in,
add them to that campaign, and activate it"

"Review all responses from this week, identify hot leads,
mark appropriate meetings as booked, and give me a summary"

"Optimize all campaigns: pause ones with < 5% response rate
and over 50 sends, suggest improvements for others"

"Create a new campaign targeted at tech companies with a
warm, conversational tone. Use inbox 2."
```

## Autonomous Mode Deep Dive

When running autonomously, the agent:

1. **Monitors Dashboard** - Checks overall health
2. **Analyzes Campaigns** - Performance review every cycle
3. **Processes Responses** - Identifies opportunities
4. **Optimizes Settings** - Pauses bad campaigns, suggests changes
5. **Reports Issues** - Alerts you of problems

### Setting Up Automatic Runs

**Option 1: Cron (Recommended for production)**
```bash
./setup_cron.sh  # Sets up hourly runs
```

**Option 2: Systemd Service (Linux)**
Create `/etc/systemd/system/crm-agent.service`:
```ini
[Unit]
Description=CRM AI Agent
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/crm
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python autonomous_agent.py --interval 3600
Restart=always

[Install]
WantedBy=multi-user.target
```

**Option 3: Background Process**
```bash
nohup python autonomous_agent.py --interval 3600 &
```

### Autonomous Decision Making

The agent makes autonomous decisions on:

**Campaign Management:**
- Pauses campaigns with < 3% response rate after 50+ sends
- Suggests sequence improvements
- Redistributes leads to better-performing campaigns

**Response Handling:**
- Identifies meeting opportunities in responses
- Flags urgent or high-value leads
- Auto-marks meetings when explicit confirmation

**Lead Management:**
- Suggests leads for new campaigns
- Identifies stale leads needing follow-up
- Categorizes leads by engagement level

**System Health:**
- Tests inbox connections
- Monitors rate limits
- Alerts on configuration issues

### Safety Guardrails

The agent has built-in safety limits:

- **Never deletes data** without explicit confirmation
- **Pauses campaigns** instead of stopping them permanently
- **Requires confirmation** for bulk operations
- **Logs all actions** in `crm_agent.log`
- **Rate limit respect** - won't override sending limits

## Logs and Monitoring

**View real-time logs:**
```bash
tail -f crm_agent.log
```

**Check cron execution:**
```bash
tail -f cron.log
```

**View conversation history:**
Stored in memory during session, not persisted between runs.

## Advanced Usage

### Custom Instructions

You can give the agent standing instructions:

```
"From now on, when analyzing campaigns, focus on tech companies"
"Always check for inbox health at the start of each conversation"
"Prioritize response rate over total volume"
```

### Integration with Other Tools

The agent can work with:
- CSV files (import/export)
- Web interface (complementary usage)
- Email clients (monitors same inboxes)

### Batch Operations

```
"For each campaign:
1. Analyze performance
2. If response rate < 5%, pause it
3. Generate a report"
```

### Scheduled Reports

```
"Every Monday, send me:
- Weekly performance summary
- Top 5 performing leads
- Campaign recommendations"
```

(Add to cron with custom command)

## Troubleshooting

### Agent not responding
- Check `ANTHROPIC_API_KEY` in `.env`
- Verify API key is valid: [console.anthropic.com](https://console.anthropic.com/)
- Check internet connection

### Tool execution errors
- Ensure database exists: `python init_db.py`
- Check database permissions
- Verify CRM web app is not corrupting database

### Autonomous mode not running
- Check cron logs: `tail -f cron.log`
- Verify cron job exists: `crontab -l`
- Check file permissions: `chmod +x autonomous_agent.py`

### Agent making unexpected decisions
- Review logs: `cat crm_agent.log`
- Adjust prompts in `crm_agent.py` SYSTEM_PROMPT
- Add more specific instructions in conversation

## Cost Management

The AI agent uses Claude Sonnet 4, which costs approximately:
- **Interactive mode**: ~$0.01-0.03 per conversation
- **Autonomous mode**: ~$0.05-0.10 per cycle
- **Daily autonomous**: ~$1.20-2.40 per day (hourly runs)

**Cost optimization tips:**
- Use `--interval 7200` (2 hours) instead of hourly
- Run autonomous mode only during business hours
- Use command mode for simple one-off tasks

## Best Practices

1. **Start with Interactive Mode** - Learn what the agent can do
2. **Review Autonomous Actions** - Check logs initially
3. **Set Clear Goals** - Tell the agent your objectives
4. **Regular Check-ins** - Review dashboard weekly
5. **Gradual Autonomy** - Start supervised, increase over time

## Examples Library

### Daily Workflow
```bash
# Morning check
python crm_agent.py --command "Give me yesterday's summary and today's priorities"

# Let agent handle the day
python autonomous_agent.py --once

# Evening review
python crm_agent.py --command "Summarize what happened today"
```

### Weekly Optimization
```bash
python crm_agent.py --command "Weekly review: analyze all campaigns, optimize underperformers, suggest new strategies"
```

### Campaign Launch
```bash
python crm_agent.py
> "I have 50 new leads from a tech conference. Create a campaign, add them, and launch it."
```

## API Reference (For Developers)

See `agent_tools.py` for available functions:

- `add_lead()` - Add single lead
- `import_leads_from_csv()` - Bulk import
- `create_campaign()` - Create with sequences
- `get_campaigns()` - List with stats
- `analyze_campaign_performance()` - Get insights
- And 15+ more functions

## Support

For issues:
1. Check logs: `crm_agent.log`
2. Review this documentation
3. Check main README.md for CRM setup issues

## Version

AI Agent v1.0.0 - Initial Release
