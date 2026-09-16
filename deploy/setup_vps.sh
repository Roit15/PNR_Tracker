#!/bin/bash
# VPS Setup Script for PNR Tracker
# Run this on your fresh Ubuntu 22.04 VPS
set -e

echo "=== PNR Tracker VPS Setup ==="

# 1. Update system
echo ">>> Updating system..."
apt-get update && apt-get upgrade -y

# 2. Install Docker
echo ">>> Installing Docker..."
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# 3. Install Docker Compose
echo ">>> Installing Docker Compose..."
apt-get install -y docker-compose-plugin

# 4. Install Nginx + Certbot
echo ">>> Installing Nginx + Certbot..."
apt-get install -y nginx certbot python3-certbot-nginx

# 5. Create app directory
echo ">>> Creating app directory..."
mkdir -p /opt/pnr-tracker
cd /opt/pnr-tracker

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Copy project files to /opt/pnr-tracker/"
echo "  2. Create .env file with your secrets"
echo "  3. Run: docker compose up -d"
echo "  4. Copy deploy/nginx.conf to /etc/nginx/sites-available/pnr"
echo "  5. ln -s /etc/nginx/sites-available/pnr /etc/nginx/sites-enabled/"
echo "  6. certbot --nginx -d balireserve.com"
echo "  7. nginx -t && systemctl reload nginx"
