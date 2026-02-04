#!/bin/bash
# Quick start script for RateTapMX CRM

echo "=========================================="
echo "RateTapMX CRM - Quick Start"
echo "=========================================="
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate venv
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt
echo "✓ Dependencies installed"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✓ .env file created (please edit with your settings)"
else
    echo "✓ .env file already exists"
fi

# Check if database exists
if [ ! -f "crm.db" ]; then
    echo ""
    read -p "Initialize database with sample data? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python init_db.py --sample
    else
        python init_db.py
    fi
else
    echo "✓ Database already exists"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "To start the CRM:"
echo "  python app.py"
echo ""
echo "Then visit: http://localhost:5000"
echo ""
echo "Default credentials:"
echo "  Username: admin"
echo "  Password: changeme"
echo ""
echo "Remember to:"
echo "  1. Edit .env with your settings"
echo "  2. Configure email inboxes in the web UI"
echo "  3. Change default password"
echo ""
