#!/usr/bin/env python3
"""
AI-Powered CRM Agent

An autonomous AI agent that manages your CRM through natural language interaction.

Usage:
    python crm_agent.py                    # Interactive chat mode
    python crm_agent.py --autonomous       # Run autonomously in background
    python crm_agent.py --command "text"   # Single command execution
"""

import os
import sys
import json
import argparse
from datetime import datetime
from anthropic import Anthropic
from agent_tools import CRMAgent
from dotenv import load_dotenv

load_dotenv()

# Initialize
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
crm = CRMAgent()

# Agent system prompt
SYSTEM_PROMPT = """You are an AI-powered CRM assistant with full autonomy to manage email campaigns, leads, and customer relationships for RateTapMX.

Your capabilities:
1. Lead Management: Add, import, update, and organize leads
2. Campaign Management: Create, activate, pause, and optimize email campaigns
3. Response Analysis: Review responses, identify opportunities, book meetings
4. Analytics: Generate insights and performance reports
5. Autonomous Operations: Make decisions to optimize campaigns and improve results

You have access to these tools via Python functions in the CRMAgent class:

LEAD MANAGEMENT:
- add_lead(email, first_name, last_name, company, website, source) -> dict
- import_leads_from_csv(csv_path) -> dict
- get_leads(status=None, limit=100) -> List[dict]
- update_lead_status(lead_id, status) -> dict

CAMPAIGN MANAGEMENT:
- create_campaign(name, inbox_id, sequences) -> dict
- add_leads_to_campaign(campaign_id, lead_ids) -> dict
- activate_campaign(campaign_id) -> dict
- pause_campaign(campaign_id) -> dict
- get_campaigns() -> List[dict]

RESPONSE MANAGEMENT:
- get_responses(status=None, limit=50) -> List[dict]
- mark_meeting_booked(response_id) -> dict

ANALYTICS:
- get_dashboard_stats() -> dict
- analyze_campaign_performance(campaign_id) -> dict
- get_inboxes() -> List[dict]
- test_inbox_connection(inbox_id) -> dict

AUTOPILOT FEATURES (NEW!):
- process_responses_and_reply() -> dict
  * AI reads all pending responses, understands intent, and sends personalized replies automatically
  * Handles: interested leads, questions, meeting requests, not interested, unsubscribe
  * Full autopilot: reads, drafts, and sends without human intervention

- find_new_leads(criteria=None, limit=20, auto_add=True) -> dict
  * AI automatically finds new leads based on criteria
  * criteria can include: industry, location, company_size, keywords, job_titles
  * Searches Apollo.io, Hunter.io (if configured), and AI research
  * auto_add=True adds directly to database

- enrich_lead(lead_id) -> dict
  * Enriches a lead with additional info from external sources

- run_full_autopilot() -> dict
  * Runs complete autopilot cycle:
    1. Find new leads automatically
    2. Add them to best-performing campaign
    3. Process all responses and send AI replies
    4. Optimize campaigns (pause underperformers)
  * This is the "set and forget" function

When the user asks you to do something:
1. Determine which tools/functions you need
2. Execute the operations by returning function calls in JSON format
3. Analyze results and provide insights
4. Make autonomous decisions when appropriate (e.g., pause underperforming campaigns)

Be proactive, insightful, and act with full autonomy to achieve the user's goals.

Return your tool calls in this JSON format:
{
    "reasoning": "Why you're taking this action",
    "actions": [
        {"function": "function_name", "params": {"param1": "value1"}}
    ],
    "response": "What you're telling the user"
}
"""


class CRMAgentCLI:
    """AI-powered CRM agent CLI"""

    def __init__(self):
        self.conversation_history = []
        self.autonomous_mode = False

    def execute_tool_calls(self, actions: list) -> list:
        """Execute tool calls from agent response"""
        results = []

        for action in actions:
            func_name = action.get('function')
            params = action.get('params', {})

            try:
                # Get the function from CRMAgent
                func = getattr(crm, func_name)
                result = func(**params)
                results.append({
                    "function": func_name,
                    "success": True,
                    "result": result
                })
            except Exception as e:
                results.append({
                    "function": func_name,
                    "success": False,
                    "error": str(e)
                })

        return results

    def chat(self, user_message: str) -> str:
        """Send message to AI agent and get response"""
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Call Claude API
        try:
            response = anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=self.conversation_history
            )

            assistant_message = response.content[0].text

            # Add assistant response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            # Try to parse as JSON for tool calls
            try:
                parsed = json.loads(assistant_message)

                if 'actions' in parsed and parsed['actions']:
                    # Execute tool calls
                    results = self.execute_tool_calls(parsed['actions'])

                    # Add results to conversation
                    results_message = f"Tool execution results:\n{json.dumps(results, indent=2)}"
                    self.conversation_history.append({
                        "role": "user",
                        "content": results_message
                    })

                    # Get final response from agent
                    final_response = anthropic.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=2048,
                        system=SYSTEM_PROMPT,
                        messages=self.conversation_history
                    )

                    final_text = final_response.content[0].text
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": final_text
                    })

                    return final_text

                # No tool calls, just return response
                return parsed.get('response', assistant_message)

            except json.JSONDecodeError:
                # Not JSON, return as is
                return assistant_message

        except Exception as e:
            return f"Error communicating with AI agent: {str(e)}"

    def interactive_mode(self):
        """Run in interactive chat mode"""
        print("=" * 60)
        print("RateTapMX CRM - AI Agent")
        print("=" * 60)
        print("I'm your autonomous CRM assistant. I can manage leads,")
        print("campaigns, analyze responses, and optimize performance.")
        print("\nType 'exit' or 'quit' to end the session.")
        print("Type 'help' for examples of what I can do.")
        print("=" * 60)
        print()

        while True:
            try:
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['exit', 'quit', 'bye']:
                    print("\nAgent: Goodbye! I'll keep monitoring your campaigns.")
                    break

                if user_input.lower() == 'help':
                    self.show_help()
                    continue

                # Get agent response
                print("\nAgent: ", end="", flush=True)
                response = self.chat(user_input)
                print(response)
                print()

            except KeyboardInterrupt:
                print("\n\nAgent: Session interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\nError: {str(e)}\n")

    def show_help(self):
        """Show help with example commands"""
        print("\n" + "=" * 60)
        print("EXAMPLES OF WHAT I CAN DO")
        print("=" * 60)
        print("""
LEAD MANAGEMENT:
  - "Add a lead: john@example.com, John Doe, Acme Corp"
  - "Import leads from sample_leads.csv"
  - "Show me all new leads"
  - "Update lead status for lead ID 5 to contacted"

CAMPAIGN MANAGEMENT:
  - "Create a 3-step sales campaign using inbox 1"
  - "Add leads 1, 2, 3 to campaign 1"
  - "Activate campaign 2"
  - "Show me all campaigns and their performance"

ANALYTICS & INSIGHTS:
  - "Give me a dashboard summary"
  - "Analyze campaign 1 performance"
  - "Which campaigns are performing best?"
  - "Show me new responses this week"

AUTONOMOUS OPERATIONS:
  - "Run optimization on all active campaigns"
  - "Review responses and book meetings for qualified leads"
  - "Monitor campaigns and alert me of any issues"

COMPLEX TASKS:
  - "Import new leads and add them to the best performing campaign"
  - "Create a new campaign for technology companies"
  - "Draft follow-up sequences for leads who haven't responded in 5 days"
        """)
        print("=" * 60 + "\n")

    def autonomous_mode_run(self):
        """Run in autonomous mode - continuously optimize CRM"""
        print("=" * 60)
        print("AUTONOMOUS MODE - AI Agent Running")
        print("=" * 60)
        print("The agent will continuously monitor and optimize your CRM.")
        print("Press Ctrl+C to stop.")
        print("=" * 60)
        print()

        tasks = [
            "Review dashboard stats and identify any issues",
            "Analyze all active campaigns for performance",
            "Check for new responses and identify meeting opportunities",
            "Optimize underperforming campaigns (pause if needed)",
            "Generate daily report with key insights"
        ]

        for task in tasks:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Task: {task}")
            print("Agent: ", end="", flush=True)

            response = self.chat(task)
            print(response)
            print("-" * 60)

        print("\n✓ Autonomous optimization complete!")
        print("Run this script regularly (via cron) for continuous management.\n")

    def execute_command(self, command: str):
        """Execute a single command"""
        print(f"Executing: {command}\n")
        response = self.chat(command)
        print(f"Agent: {response}\n")


def main():
    parser = argparse.ArgumentParser(description='AI-powered CRM Agent')
    parser.add_argument('--autonomous', action='store_true',
                       help='Run in autonomous mode (optimize and report)')
    parser.add_argument('--command', type=str,
                       help='Execute a single command')
    args = parser.parse_args()

    # Check for API key
    if not os.getenv('ANTHROPIC_API_KEY'):
        print("Error: ANTHROPIC_API_KEY not found in environment variables")
        print("\nPlease set your Anthropic API key:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        print("  # Or add to .env file")
        print("\nGet your API key at: https://console.anthropic.com/")
        sys.exit(1)

    agent = CRMAgentCLI()

    if args.autonomous:
        agent.autonomous_mode_run()
    elif args.command:
        agent.execute_command(args.command)
    else:
        agent.interactive_mode()


if __name__ == '__main__':
    main()
