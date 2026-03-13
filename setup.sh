#!/bin/bash
# PNR Tracker Setup Script
# Run this once to set up the project

set -e

echo "🚀 Setting up PNR Tracker..."

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright browsers
echo "🌐 Installing Playwright browsers (Chromium)..."
playwright install chromium

# Install pytz for timezone support
pip install pytz

# Create uploads directory
mkdir -p uploads screenshots

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env with your settings:"
    echo "   - SMTP_EMAIL (your Gmail address)"
    echo "   - SMTP_PASSWORD (Gmail App Password)"
    echo "   - RECIPIENT_EMAIL (email to receive updates)"
    echo "   - PASSENGER_LASTNAME (your last name on Indigo bookings)"
    echo ""
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your email and Indigo details"
echo "  2. Run: source venv/bin/activate"
echo "  3. Run: python app.py"
echo "  4. Open: http://localhost:5000"
echo ""
