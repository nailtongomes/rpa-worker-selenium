# rpa-worker-selenium Dockerfile (Chromium fallback version)
# Use this version if you cannot access Google Chrome downloads
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    DISPLAY=:99 \
    SCREEN_WIDTH=1366 \
    SCREEN_HEIGHT=768 \
    HOME=/app

# Install runtime dependencies for browsers and automation
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    xvfb \
    x11vnc \
    x11-utils \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libx11-xcb1 \
    libxt6 \
    libxdamage1 \
    libnss3 \
    libcups2 \
    libxss1 \
    libasound2 \
    procps \
    libpangocairo-1.0-0 \
    libu2f-udev \
    libvulkan1 \
    curl \
    fonts-liberation \
    libnss3-tools \
    openssl \
    sudo \
    openbox \
    xdotool \
    imagemagick \
    x11-apps \
    ghostscript \
    bc zip unzip \
    && apt-get install -y --fix-missing zip \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for compatibility with scripts expecting google-chrome
RUN ln -sf /usr/bin/chromium /usr/bin/google-chrome \
    && ln -sf /usr/bin/chromedriver /usr/local/bin/chromedriver

# Create non-root user
RUN useradd -m -d /app -u 1000 rpauser \
 && echo "rpauser ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Set up working directory structure
WORKDIR /app
RUN mkdir -p /app/scripts /app/logs /app/tmp \
    /app/.pki/nssdb \
    && chmod 1777 /app/tmp \
    && chmod 700 /app/.pki/nssdb \
    && chown -R rpauser:rpauser /app

# Install Python dependencies
COPY requirements.txt .
RUN python -m pip install --upgrade --trusted-host pypi.org --trusted-host files.pythonhosted.org pip \
 && pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy application files
COPY . .

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh /app/script_downloader.py /app/smoke_test.py

# Environment variables for control (all optional; defaults to lightweight/headless)
ENV USE_XVFB=0 \
    USE_OPENBOX=0 \
    USE_VNC=0 \
    VNC_PORT=5900

# Switch to non-root user
USER rpauser

# Set up entrypoint for dynamic script execution with download support
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden)
CMD ["python", "--version"]
