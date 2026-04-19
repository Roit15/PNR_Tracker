#!/bin/bash
# PNR Tracker Startup Script
# Starts the Flask app + Cloudflare Tunnel

APP_DIR="/Users/jangr/vibeCoding/PNR_Tracker"
VENV="$APP_DIR/venv/bin/activate"
LOG_DIR="$APP_DIR/logs"
CLOUDFLARED="/tmp/cloudflared"

mkdir -p "$LOG_DIR"

# Activate venv and start Flask app
cd "$APP_DIR"
source "$VENV"
python app.py >> "$LOG_DIR/app.log" 2>&1
