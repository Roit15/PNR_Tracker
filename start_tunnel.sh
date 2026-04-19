#!/bin/bash
# Cloudflare Named Tunnel Startup Script
# Connects the 'pnr' named tunnel to localhost:8080

LOG_DIR="/Users/jangr/vibeCoding/PNR_Tracker/logs"
CLOUDFLARED="/Users/jangr/.local/bin/cloudflared"
TUNNEL_TOKEN="eyJhIjoiMmIwMzQ4ZjNkOTczN2Y5ZDg4Yzk1MTgzMTFmZTJjNzUiLCJzIjoiZzJvcFJaS1E1TEo2U0hjVXpKdjN3c3N4bGVkM2xNYjhSSFpxc3JhMVNGRT0iLCJ0IjoiYzJhMDJhZDktODk0OC00YzVkLThiZTEtOTU1ZTE0ZjU5N2ZkIn0="

mkdir -p "$LOG_DIR"

# Wait for the Flask app to be ready
for i in $(seq 1 30); do
    curl -s -o /dev/null http://localhost:8080 && break
    sleep 2
done

# Run named tunnel
"$CLOUDFLARED" tunnel run --token "$TUNNEL_TOKEN" >> "$LOG_DIR/tunnel.log" 2>&1
