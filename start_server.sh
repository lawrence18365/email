#!/bin/bash
# Start the Wedding Counselors email server
# This runs the Flask app with the background scheduler

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Kill any existing server
pkill -f "python app.py" 2>/dev/null

echo "Starting Wedding Counselors Email Server..."
echo "Dashboard: http://localhost:5001"
echo ""
echo "Scheduler will automatically:"
echo "  - Send emails every hour (during business hours 9am-5pm)"
echo "  - Check for responses every 10 minutes"
echo "  - Process ~10-15 emails per day"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python app.py
