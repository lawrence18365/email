# Quick Start: AI Agent

Get started with the AI CRM Agent in 5 minutes.

## Prerequisites

- Python 3.10+
- RateTapMX CRM installed (see main README.md)
- Anthropic API key ([get one here](https://console.anthropic.com/))

## Step 1: Get API Key

1. Visit [console.anthropic.com](https://console.anthropic.com/)
2. Sign up or log in
3. Create a new API key
4. Copy the key (starts with `sk-ant-...`)

## Step 2: Configure

Add your API key to `.env`:

```bash
echo "ANTHROPIC_API_KEY=your-key-here" >> .env
```

Or edit `.env` manually and add:
```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

## Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

(This installs the `anthropic` package)

## Step 4: Start Chatting

```bash
python crm_agent.py
```

## First Commands to Try

Once the agent starts, try these:

### 1. Get Overview
```
You: Give me a dashboard summary
```

### 2. Add a Lead
```
You: Add a lead: john@techcorp.com, John Smith, TechCorp, https://techcorp.com
```

### 3. Import Leads
```
You: Import leads from sample_leads.csv
```

### 4. Check Campaigns
```
You: Show me all campaigns and their performance
```

### 5. Create a Campaign
```
You: Create a 3-step sales campaign using inbox 1 with these emails:
- Day 0: Introduction
- Day 3: Follow-up with case study
- Day 7: Final offer
```

### 6. Analyze Performance
```
You: Which campaign is performing best and why?
```

### 7. Complex Task
```
You: Import sample_leads.csv, analyze which leads are tech companies,
create a campaign for them, and activate it
```

## Enable Autonomous Mode

Let the agent manage your CRM automatically:

### One-Time Run
```bash
python autonomous_agent.py --once
```

### Continuous (every hour)
```bash
python autonomous_agent.py --interval 3600
```

### Automatic (cron)
```bash
./setup_cron.sh
```

This sets up the agent to run every hour automatically.

## What Happens in Autonomous Mode?

Every cycle, the agent:

1. ✅ Reviews dashboard for issues
2. ✅ Analyzes campaign performance
3. ✅ Checks for new responses
4. ✅ Pauses underperforming campaigns (< 3% response rate)
5. ✅ Identifies meeting opportunities
6. ✅ Tests inbox connections
7. ✅ Generates insights report

All actions are logged to `crm_agent.log`

## Viewing Logs

```bash
# Real-time log viewing
tail -f crm_agent.log

# View last 50 lines
tail -50 crm_agent.log

# Search logs for specific campaigns
grep "Campaign" crm_agent.log
```

## Common Use Cases

### Daily Workflow

**Morning:**
```bash
python crm_agent.py --command "What happened yesterday? Any urgent items?"
```

**During Day:**
Let autonomous mode handle everything (via cron)

**Evening:**
```bash
python crm_agent.py --command "Summarize today's activity"
```

### Weekly Review

```bash
python crm_agent.py --command "Give me a weekly performance report with recommendations"
```

### Campaign Launch

```bash
python crm_agent.py
> "I have 50 new leads from TechConf. Create a campaign, add them, and launch."
```

## Tips

1. **Be Specific**: "Create a 3-step campaign" is better than "create a campaign"
2. **Ask Questions**: The agent can explain its decisions
3. **Review Initially**: Check `crm_agent.log` for first few autonomous runs
4. **Iterate**: Refine campaigns based on agent insights

## Troubleshooting

**"ANTHROPIC_API_KEY not found"**
- Check `.env` file exists
- Verify key is on its own line: `ANTHROPIC_API_KEY=sk-ant-...`
- No spaces around the `=`

**"Error communicating with AI agent"**
- Check internet connection
- Verify API key is valid at [console.anthropic.com](https://console.anthropic.com/)
- Check you have API credits

**Agent makes unexpected decisions**
- Review actions in `crm_agent.log`
- Adjust by giving more specific instructions
- Disable autonomous mode temporarily

**Database errors**
- Ensure database is initialized: `python init_db.py`
- Check `crm.db` file exists
- Make sure web app isn't running simultaneously

## Cost Estimate

Using Claude Sonnet 4:

- **Interactive session**: ~$0.02 per conversation
- **Single command**: ~$0.01 per command
- **Autonomous cycle**: ~$0.08 per run
- **Hourly autonomous**: ~$1.92 per day (~$58/month)

**To reduce costs:**
- Use 2-hour intervals: `--interval 7200` (~$29/month)
- Run only during business hours (8am-6pm)
- Use command mode for simple tasks

## Next Steps

1. ✅ Try interactive mode
2. ✅ Import your real leads
3. ✅ Create your first campaign
4. ✅ Let autonomous mode run for a day
5. ✅ Review results and iterate

## Full Documentation

- **Comprehensive Guide**: [AGENT_README.md](AGENT_README.md)
- **CRM Basics**: [README.md](README.md)
- **API Reference**: See `agent_tools.py`

## Support

- Check logs: `tail -f crm_agent.log`
- Review documentation: `AGENT_README.md`
- Test without AI: Use web interface at `http://localhost:5000`

## Example Session

```
$ python crm_agent.py

You: Give me a dashboard summary

Agent: Here's your current CRM status:

📊 Overview:
- Total leads: 145
- Active campaigns: 3
- Emails sent today: 47 (within rate limits)
- Responses this week: 12
- Meetings booked: 5

🎯 Campaign Performance:
1. "Q1 Sales Outreach" - 18.5% response rate ⭐
2. "Product Launch" - 12.1% response rate
3. "Re-engagement" - 4.2% response rate ⚠️

⚠️ Alert: Campaign 3 "Re-engagement" has low performance.
   Consider pausing or revising the messaging.

💡 Opportunity: You have 3 unreviewed responses from this week.
   One mentions "interested in pricing" - potential hot lead!

What would you like me to do?

You: Pause campaign 3 and show me that hot lead

Agent: ✅ Paused campaign "Re-engagement"

🔥 Hot Lead:
From: Sarah Johnson (sarah@growthco.com)
Company: Growth Co
Received: 2 days ago

Message excerpt:
"Thanks for reaching out. We're actually interested in learning
more about your pricing and implementation timeline. Can we
schedule a call this week?"

Status: Responded (not yet marked as meeting)

Would you like me to mark this as meeting booked?

You: Yes

Agent: ✅ Marked as meeting booked
✅ Updated lead status to "meeting_booked"
✅ Stopped all further sequence emails

Great! Make sure to follow up with Sarah to schedule the actual meeting.

You: Thanks! Run in autonomous mode from now on

Agent: Perfect! I'll monitor everything continuously.

To enable:
1. Run: ./setup_cron.sh (for automatic hourly runs)
2. Or: python autonomous_agent.py --interval 3600 (continuous)

I'll handle:
- Campaign optimization
- Response monitoring
- Lead management
- Performance alerts

You can always check my work in crm_agent.log

Goodbye!
```

---

**You're ready!** Start with `python crm_agent.py` and let the AI manage your CRM.
