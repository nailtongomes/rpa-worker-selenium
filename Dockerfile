# rpa-worker-selenium Dockerfile
# Multi-stage build for optimized image size
FROM python:3.11-slim-bookworm AS builder

ARG CHROME_VERSION=142.0.7444.162
ARG BUILD_PJEOFFICE=0
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /downloads
# Download Chrome and ChromeDriver from Chrome for Testing
RUN curl -Lo "chromedriver-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip" \
 && curl -Lo "chrome-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip" \
 && unzip chromedriver-linux64.zip \
 && unzip chrome-linux64.zip

# ---------- STAGE 2: runtime
FROM python:3.11-slim-bookworm

# Pass build argument to runtime stage
ARG BUILD_PJEOFFICE=0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    DISPLAY=:99 \
    SCREEN_WIDTH=1366 \
    SCREEN_HEIGHT=768 \
    HOME=/app \
    MOZ_ALLOW_ROOT=1

# Install runtime dependencies for browsers and automation
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
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
        openjdk-17-jre-headless \
        ffmpeg \
        atk \
        libatk-bridge2.0-0 \
        libxcomposite1 \
        libxrandr2 \
        libgbm1 \
        libxkbcommon0 \
        libxfixes3 \
    && rm -rf /var/lib/apt/lists/*

# Copy Chrome and ChromeDriver from builder stage
COPY --from=builder /downloads/chrome-linux64 /opt/chrome
COPY --from=builder /downloads/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver

# Create symbolic links and set permissions
RUN ln -s /opt/chrome/chrome /usr/local/bin/chrome \
    && ln -s /opt/chrome/chrome /usr/local/bin/google-chrome \
    && chmod +x /usr/local/bin/chromedriver \
    && chmod +x /opt/chrome/chrome

# Create non-root user
RUN useradd -m -d /app -u 1000 rpauser \
 && echo "rpauser ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Set up working directory structure
WORKDIR /app
RUN mkdir -p /app/src /app/logs /app/tmp /app/recordings \
    /app/.pki/nssdb \
    /app/.cache \
    /data \
    && chmod 1777 /app/tmp \
    && chmod 700 /app/.pki/nssdb \
    && chmod 777 /data \
    && chmod 777 /app/recordings \
    && chown -R rpauser:rpauser /app

# Set up OpenBox configuration to prevent menu warnings
RUN mkdir -p /var/lib/openbox && \
    echo '<?xml version="1.0" encoding="UTF-8"?>' > /var/lib/openbox/debian-menu.xml && \
    echo '<openbox_menu xmlns="http://openbox.org/3.4/menu">' >> /var/lib/openbox/debian-menu.xml && \
    echo '    <menu id="root-menu" label="Openbox 3">' >> /var/lib/openbox/debian-menu.xml && \
    echo '        <item label="Terminal">' >> /var/lib/openbox/debian-menu.xml && \
    echo '            <action name="Execute"><command>xterm</command></action>' >> /var/lib/openbox/debian-menu.xml && \
    echo '        </item>' >> /var/lib/openbox/debian-menu.xml && \
    echo '    </menu>' >> /var/lib/openbox/debian-menu.xml && \
    echo '</openbox_menu>' >> /var/lib/openbox/debian-menu.xml && \
    chmod 644 /var/lib/openbox/debian-menu.xml

# Optional: Install PJeOffice (controlled by BUILD_PJEOFFICE build argument)
RUN if [ "$BUILD_PJEOFFICE" = "1" ]; then \
    mkdir -p /opt/pjeoffice && \
    cd /tmp && \
    curl -Lo "pjeoffice.zip" "https://pje-office.pje.jus.br/pro/pjeoffice-pro-v2.5.16u-linux_x64.zip" && \
    unzip pjeoffice.zip && \
    cp -r pjeoffice-pro/* /opt/pjeoffice/ && \
    rm -rf pjeoffice.zip pjeoffice-pro && \
    chown -R rpauser:rpauser /opt/pjeoffice && \
    chmod -R 755 /opt/pjeoffice && \
    chmod +x /opt/pjeoffice/pjeoffice-pro.sh && \
    mkdir -p /app/.pjeoffice-pro && \
    chown -R rpauser:rpauser /app/.pjeoffice-pro && \
    chmod -R 755 /app/.pjeoffice-pro; \
fi

# Install Python dependencies
COPY requirements.txt .
RUN python -m pip install --upgrade --trusted-host pypi.org --trusted-host files.pythonhosted.org pip \
 && pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt \
 && chmod -R 777 /usr/local/lib/python3.11/site-packages/seleniumbase/drivers || true

# Copy application files
COPY . .

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh /app/script_downloader.py /app/smoke_test.py

# Environment variables for control (all optional; defaults to lightweight/headless)
ENV USE_XVFB=0 \
    USE_OPENBOX=0 \
    USE_VNC=0 \
    USE_PJEOFFICE=0 \
    USE_SCREEN_RECORDING=0 \
    VNC_PORT=5900 \
    RECORDING_DIR=/app/recordings \
    XDG_CACHE_HOME=/app/.cache

# Run as root user (rpauser kept for compatibility but not used)
# USER rpauser

# Set up entrypoint for dynamic script execution with download support
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden)
CMD ["python", "--version"]
