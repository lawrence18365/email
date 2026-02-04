#!/bin/bash
# Setup cron job for autonomous CRM agent

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Setting up autonomous CRM agent cron job..."
echo ""
echo "This will run the agent every hour to optimize your CRM."
echo ""

# Create cron job entry
CRON_JOB="0 * * * * cd $SCRIPT_DIR && $SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/autonomous_agent.py --once >> $SCRIPT_DIR/cron.log 2>&1"

echo "Cron job to be added:"
echo "$CRON_JOB"
echo ""

read -p "Add this cron job? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "✓ Cron job added successfully!"
    echo ""
    echo "The agent will now run every hour automatically."
    echo "To view logs: tail -f $SCRIPT_DIR/crm_agent.log"
    echo "To remove: crontab -e (and delete the line)"
else
    echo "Cron job not added."
    echo ""
    echo "To run manually:"
    echo "  python autonomous_agent.py --once     # Run once"
    echo "  python autonomous_agent.py            # Run continuously"
fi

echo ""
