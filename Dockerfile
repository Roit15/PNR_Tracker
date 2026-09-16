FROM python:3.11-slim

# Install Chrome + Xvfb + psycopg2 build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 unzip xvfb \
    fonts-liberation libappindicator3-1 libasound2 libatk-bridge2.0-0 \
    libatk1.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 \
    libnspr4 libnss3 libx11-xcb1 libxcomposite1 libxdamage1 \
    libxrandr2 xdg-utils libxss1 libxtst6 ca-certificates \
    libpq-dev gcc \
    libglib2.0-0 libexpat1 libxcb1 libxkbcommon0 libx11-6 \
    libxext6 libxfixes3 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# Set display for Xvfb
ENV DISPLAY=:99

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium for SriLankan scraper)
RUN playwright install chromium

# Copy app code (respects .dockerignore)
COPY . .

# Create necessary directories
RUN mkdir -p uploads screenshots

# Expose port
EXPOSE 8080

# Start Xvfb + app (cleanup lock first)
CMD rm -f /tmp/.X*lock && \
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp & \
    sleep 1 && \
    python app.py
