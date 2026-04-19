#!/bin/bash
# Script to run the PNR Tracker apps persistently in the background

APP_DIR="/Users/jangr/vibeCoding/PNR_Tracker"
LOG_DIR="$APP_DIR/logs"

# Ensure logs dir exists
mkdir -p "$LOG_DIR"

# Kill existing processes
echo "Killing any existing web app and tunnel instances..."
pkill -f "python app.py"
pkill -f "cloudflared tunnel run"

# Wait to ensure they are killed
sleep 2

# Start the Flask app in the background
echo "Starting Flask app in background..."
nohup bash "$APP_DIR/start_app.sh" > "$LOG_DIR/nohup_app.out" 2>&1 &

# Start the Cloudflare Tunnel in the background
echo "Starting Cloudflare Tunnel in background..."
nohup bash "$APP_DIR/start_tunnel.sh" > "$LOG_DIR/nohup_tunnel.out" 2>&1 &

echo "Both services started in the background!"
echo "You can check the logs in $LOG_DIR"
