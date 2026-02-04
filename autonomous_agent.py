#!/usr/bin/env python3
"""
Autonomous CRM Agent - Background Runner

Runs the AI agent continuously to monitor and optimize campaigns.
Can be scheduled via cron or run as a daemon.

Usage:
    python autonomous_agent.py --interval 3600    # Run every hour
    python autonomous_agent.py --once             # Run once and exit
"""

import time
import argparse
import logging
from datetime import datetime
from crm_agent import CRMAgentCLI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crm_agent.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class AutonomousRunner:
    """Runs the CRM agent autonomously in background"""

    def __init__(self):
        self.agent = CRMAgentCLI()
        self.agent.autonomous_mode = True

    def run_optimization_cycle(self):
        """Run a single optimization cycle"""
        logger.info("="*60)
        logger.info("Starting autonomous optimization cycle")
        logger.info("="*60)

        tasks = [
            {
                "name": "Dashboard Review",
                "command": "Check dashboard stats and alert me of any critical issues or opportunities"
            },
            {
                "name": "Campaign Performance Analysis",
                "command": "Analyze all active campaigns. Pause any with response rate < 3% and over 50 emails sent. Suggest improvements."
            },
            {
                "name": "Response Processing",
                "command": "Check for new responses. Identify any that indicate strong interest in booking meetings. Mark appropriate ones as meeting_booked if they explicitly mention wanting to meet."
            },
            {
                "name": "Lead Management",
                "command": "Review lead statuses. Suggest any leads that should be added to campaigns or followed up with."
            },
            {
                "name": "Inbox Health Check",
                "command": "Check all inbox connections are working properly. Alert if any issues."
            }
        ]

        results = []

        for task in tasks:
            logger.info(f"\n--- {task['name']} ---")
            try:
                response = self.agent.chat(task['command'])
                logger.info(f"Response: {response}")
                results.append({
                    "task": task['name'],
                    "success": True,
                    "response": response
                })
            except Exception as e:
                logger.error(f"Error in {task['name']}: {str(e)}")
                results.append({
                    "task": task['name'],
                    "success": False,
                    "error": str(e)
                })

        # Generate summary
        logger.info("\n" + "="*60)
        logger.info("CYCLE SUMMARY")
        logger.info("="*60)

        summary_prompt = f"""
Based on the tasks completed in this cycle, generate a brief executive summary:

Tasks completed: {len([r for r in results if r['success']])} / {len(results)}

Please provide:
1. Key actions taken
2. Important alerts or issues
3. Recommendations for next steps

Keep it concise (3-5 bullet points).
"""

        try:
            summary = self.agent.chat(summary_prompt)
            logger.info(f"\n{summary}")
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")

        logger.info("\n" + "="*60)
        logger.info("Optimization cycle complete")
        logger.info("="*60 + "\n")

        return results

    def run_continuous(self, interval_seconds: int = 3600):
        """Run continuously with specified interval"""
        logger.info(f"Starting continuous autonomous mode (interval: {interval_seconds}s)")

        try:
            while True:
                self.run_optimization_cycle()

                logger.info(f"Sleeping for {interval_seconds} seconds...")
                logger.info(f"Next run at: {datetime.fromtimestamp(time.time() + interval_seconds)}")
                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("\n\nAutonomous agent stopped by user")
        except Exception as e:
            logger.error(f"Fatal error in autonomous mode: {str(e)}")
            raise

    def run_once(self):
        """Run a single optimization cycle and exit"""
        logger.info("Running single optimization cycle")
        self.run_optimization_cycle()
        logger.info("Single cycle complete - exiting")


def main():
    parser = argparse.ArgumentParser(description='Autonomous CRM Agent Runner')
    parser.add_argument('--interval', type=int, default=3600,
                       help='Interval between runs in seconds (default: 3600 = 1 hour)')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (useful for cron jobs)')
    args = parser.parse_args()

    runner = AutonomousRunner()

    if args.once:
        runner.run_once()
    else:
        runner.run_continuous(args.interval)


if __name__ == '__main__':
    main()
