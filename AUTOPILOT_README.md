# Full Autopilot Mode - AI Sales Assistant

Your CRM now runs on full autopilot. The AI will:
1. **Find new leads** automatically
2. **Send outreach emails** via campaigns
3. **Read and understand responses**
4. **Reply like a human assistant**
5. **Book meetings** when prospects are interested

## Quick Start

### Option 1: One Command Autopilot

```bash
python crm_agent.py --command "run_full_autopilot"
```

This single command:
- Finds 10 new leads automatically
- Adds them to your best-performing campaign
- Processes all pending responses with AI replies
- Optimizes campaigns (pauses underperformers)

### Option 2: Interactive Autopilot

```bash
python crm_agent.py
```

Then say:
```
You: Run full autopilot
You: Find 20 new leads in the fintech industry
You: Process all responses and reply automatically
```

### Option 3: Background Autopilot (24/7)

```bash
python app.py
```

The scheduler automatically runs:
- **Every 15 minutes**: AI reads responses and sends replies
- **9 AM & 3 PM daily**: AI finds new leads
- **Hourly**: Sends campaign emails (respects rate limits)

## What the AI Does

### 1. Lead Finding (Prospecting)

The AI finds leads through:
- **Apollo.io** (if API key configured)
- **Hunter.io** (if API key configured)
- **AI Research** (always available - uses Claude to research companies)

**Default criteria:**
- Industry: Financial services, mortgage, real estate, fintech
- Location: Mexico, Latin America
- Company size: Small to medium businesses
- Job titles: CEO, CFO, Owner, Director of Sales, Marketing Manager

**Customize via chat:**
```
You: Find 30 leads in the technology industry in the USA, targeting CTOs
```

### 2. AI Email Replies

When someone responds to your outreach, the AI:

1. **Analyzes intent** - Is this person interested? Do they have questions? Not interested?

2. **Categorizes response:**
   - `interested` - Wants to learn more
   - `meeting_request` - Explicitly wants to meet
   - `question` - Has specific questions
   - `not_interested` - Polite decline
   - `unsubscribe` - Wants off the list
   - `out_of_office` - Auto-reply (ignored)

3. **Generates personalized reply** - Based on their message and intent

4. **Sends automatically** - Full autopilot, no approval needed

**Example AI Conversation:**

*Lead's response:*
> "Thanks for reaching out. We're actually looking at solutions like this. Can you tell me more about pricing?"

*AI's reply:*
> Hi John,
>
> Great to hear from you! I'd be happy to walk you through our pricing.
>
> RateTapMX offers flexible plans based on your needs. For a company like TechCorp, most clients find our Professional tier ($X/month) covers everything.
>
> Would it be easier to hop on a quick call? I can answer all your questions and show you exactly how it would work for your team.
>
> Feel free to book a time: https://calendly.com/ratetapmx/30min
>
> Best regards,
> RateTapMX Team

### 3. Meeting Booking

When the AI detects meeting interest:
- Includes your Calendly link automatically
- Marks lead as "meeting_booked" when confirmed
- Stops further campaign emails

**Configure your Calendly link in `.env`:**
```
CALENDLY_LINK=https://calendly.com/your-link/30min
```

### 4. Campaign Optimization

The AI automatically:
- **Pauses campaigns** with < 3% response rate (after 50+ sends)
- **Distributes new leads** to best-performing campaigns
- **Generates insights** on what's working

## Configuration

### Required: Anthropic API Key

```bash
# In .env file
ANTHROPIC_API_KEY=sk-ant-...
```

Get from: [console.anthropic.com](https://console.anthropic.com/)

### Optional: Lead Prospecting Services

These improve lead quality but are not required:

```bash
# Apollo.io - Best for finding leads
APOLLO_API_KEY=your-key

# Hunter.io - Email verification
HUNTER_API_KEY=your-key

# Clearbit - Lead enrichment
CLEARBIT_API_KEY=your-key
```

**Without these keys**: AI uses research mode (still finds leads, just through Claude's knowledge)

**With these keys**: Real-time data, verified emails, better accuracy

### Meeting Link

```bash
CALENDLY_LINK=https://calendly.com/ratetapmx/30min
```

Or use Cal.com, HubSpot meetings, etc.

## How It Works (Technical)

### AI Responder Flow

```
1. New email arrives in inbox
   ↓
2. Scheduler checks every 10 min (check_responses)
   ↓
3. Email saved to database with lead info
   ↓
4. Auto-reply scheduler runs every 15 min
   ↓
5. AI analyzes intent:
   - Calls Claude with email content
   - Returns: intent, sentiment, urgency, key_points
   ↓
6. AI generates reply:
   - Personalized based on intent
   - Addresses their specific points
   - Includes meeting link if appropriate
   ↓
7. Email sent via SMTP
   ↓
8. Lead status updated
   ↓
9. Further campaign emails stopped (if responded)
```

### Lead Finder Flow

```
1. Scheduler runs at 9 AM and 3 PM
   ↓
2. AI searches for leads:
   - Apollo.io API (if configured)
   - Hunter.io API (if configured)
   - AI research (always)
   ↓
3. Leads deduplicated by email
   ↓
4. Added to database (status: new)
   ↓
5. Full autopilot adds to best campaign
   ↓
6. Campaign sends first email
```

## CLI Commands

### Interactive Mode

```bash
python crm_agent.py
```

**Autopilot commands:**
```
"Run full autopilot"
"Find new leads"
"Find 50 leads in healthcare industry"
"Process responses and reply"
"Show me what the AI replied today"
```

**Combined commands:**
```
"Find 20 tech leads, add them to campaign 1, and activate it"
"Process all responses, then show me a summary"
```

### Single Command Mode

```bash
# Full autopilot cycle
python crm_agent.py --command "run_full_autopilot"

# Just find leads
python crm_agent.py --command "find_new_leads with criteria for fintech in Mexico"

# Just process responses
python crm_agent.py --command "process_responses_and_reply"
```

### Background Mode

```bash
# Start web app with scheduler (includes autopilot)
python app.py

# Or run autonomous agent
python autonomous_agent.py --interval 3600
```

## Monitoring

### View AI Activity

```bash
# Real-time logs
tail -f crm_agent.log

# See what AI replied
grep "Auto-replied" crm_agent.log

# See leads found
grep "Prospecting" crm_agent.log
```

### Dashboard Stats

```bash
python crm_agent.py --command "get_dashboard_stats"
```

### Response Analysis

```bash
python crm_agent.py
> "Show me all responses from this week and what the AI replied"
```

## Safety Features

### Built-in Guardrails

1. **Rate Limiting**: Respects your email rate limits (default 5/hour/inbox)
2. **Unsubscribe Handling**: Automatically removes people who ask
3. **Out-of-Office Detection**: Ignores auto-replies
4. **Spam Filtering**: Ignores irrelevant responses
5. **Confidence Threshold**: Won't auto-send if unsure (< 50% confidence)
6. **Logging**: Every action is logged for review

### What AI Won't Do

- Delete leads without confirmation
- Send more than rate limit allows
- Reply to obvious spam/auto-replies
- Override your campaign settings
- Send to unsubscribed emails

## Customization

### Modify AI Reply Style

Edit `ai_responder.py` - `REPLY_GENERATION_PROMPT`:

```python
REPLY_GENERATION_PROMPT = """You are a friendly, professional sales assistant...

# Add your customizations:
- Always mention [specific product feature]
- Use [your brand voice]
- Include [your value proposition]
"""
```

### Modify Lead Search Criteria

Edit defaults in `lead_finder.py` or pass custom criteria:

```python
criteria = {
    "industry": "healthcare, medical devices",
    "location": "California, Texas",
    "company_size": "50-500 employees",
    "keywords": ["hospital", "clinic", "medical"],
    "job_titles": ["CEO", "COO", "Director of Operations"]
}
```

### Adjust Autopilot Frequency

Edit `scheduler.py`:

```python
# AI auto-reply frequency (default: 15 minutes)
trigger=IntervalTrigger(minutes=15)

# Lead prospecting schedule (default: 9 AM and 3 PM)
hour='9,15'
```

## Cost Estimate

### Anthropic API (Required)

Per autopilot cycle:
- Intent analysis: ~$0.01 per response
- Reply generation: ~$0.02 per reply
- Lead prospecting: ~$0.05 per search

**Monthly estimate (active usage):**
- 100 responses/month: ~$3
- 500 responses/month: ~$15
- Lead prospecting (2x daily): ~$10

### Lead Services (Optional)

- **Apollo.io**: Free tier available, paid from $49/month
- **Hunter.io**: Free 25 searches/month, paid from $49/month
- **Clearbit**: Contact for pricing

**Recommendation**: Start without these, add if you need higher volume/accuracy

## Troubleshooting

### AI Not Replying

1. Check Anthropic API key: `echo $ANTHROPIC_API_KEY`
2. Check scheduler is running: `tail -f` logs
3. Verify responses exist: Check web UI or `get_responses(status='new')`

### Low-Quality Leads

1. Add Apollo.io or Hunter.io API keys
2. Customize search criteria
3. Adjust target industries/locations

### Replies Too Generic

1. Edit `REPLY_GENERATION_PROMPT` in `ai_responder.py`
2. Add more context about your product
3. Include example replies you like

### Too Many Emails Being Sent

1. Reduce rate limit in `.env`: `MAX_EMAILS_PER_HOUR=3`
2. Pause campaigns: `pause_campaign(campaign_id)`
3. Adjust prospecting frequency in `scheduler.py`

## Summary

Your CRM now operates like having a full-time sales assistant that:

| Task | Manual Effort | With Autopilot |
|------|---------------|----------------|
| Find leads | Hours of research | Automatic |
| Send outreach | Manual or scheduled | Automatic |
| Read responses | Check inbox constantly | Automatic |
| Reply to leads | Write each reply | AI writes & sends |
| Book meetings | Back-and-forth emails | AI includes link |
| Track status | Manual updates | Automatic |

**Total human effort required**: Review daily summary, adjust strategy as needed

**Everything else**: The AI handles it.

---

## Quick Reference

```bash
# Start everything (web UI + autopilot)
python app.py

# Interactive AI chat
python crm_agent.py

# Single autopilot run
python crm_agent.py --command "run_full_autopilot"

# View logs
tail -f crm_agent.log

# Check status
python crm_agent.py --command "get_dashboard_stats"
```

**Your CRM is now on autopilot!** 🚀
