# rpa-worker-selenium Dockerfile (Unified)
# Multi-browser support with build arg to choose webdriver
# Supports: chrome (default), brave
# Multi-stage build for optimized image size

# ============================
# STAGE 1: Builder (Chrome downloads)
# ============================
FROM python:3.11-slim-bookworm AS builder

ARG BROWSER_TYPE=chrome
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /downloads

# Download Chrome and ChromeDriver only if BROWSER_TYPE is chrome
# Create placeholder files for COPY compatibility when not building chrome
RUN if [ "$BROWSER_TYPE" = "chrome" ]; then \
        echo "Downloading Google Chrome..."; \
        wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; \
        CHROMEDRIVER_VERSION=$(curl -sS https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE) && \
        curl -Lo "chromedriver-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" && \
        unzip chromedriver-linux64.zip; \
    else \
        echo "Creating placeholder files for non-chrome builds"; \
        touch google-chrome-stable_current_amd64.deb; \
        mkdir -p chromedriver-linux64 && touch chromedriver-linux64/chromedriver; \
    fi

# ============================
# STAGE 2: Runtime
# ============================
FROM python:3.11-slim-bookworm

# Build arguments
ARG BUILD_PJEOFFICE=0
ARG BROWSER_TYPE=chrome

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    DISPLAY=:99 \
    SCREEN_WIDTH=1366 \
    SCREEN_HEIGHT=768 \
    HOME=/app \
    MOZ_ALLOW_ROOT=1 \
    BROWSER_TYPE=${BROWSER_TYPE}

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
        ffmpeg \
        openjdk-17-jre-headless \
        libxcomposite1 \
        libxrandr2 \
        libgbm1 \
        libxkbcommon0 \
        libxfixes3 \
        gnupg \
        apt-transport-https \
        ca-certificates \
        git \
        net-tools \
    && rm -rf /var/lib/apt/lists/*

# Install browser and driver based on BROWSER_TYPE
RUN if [ "$BROWSER_TYPE" = "chrome" ]; then \
        echo "Setting up Google Chrome..."; \
    elif [ "$BROWSER_TYPE" = "brave" ]; then \
        echo "Installing Brave Browser..."; \
        curl -fsSL https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg | gpg --dearmor -o /usr/share/keyrings/brave-browser-archive-keyring.gpg && \
        echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg arch=amd64] https://brave-browser-apt-release.s3.brave.com/ stable main" | tee /etc/apt/sources.list.d/brave-browser-release.list && \
        apt-get update && \
        apt-get install -y brave-browser && \
        rm -rf /var/lib/apt/lists/* && \
        ln -sf /usr/bin/brave-browser /usr/bin/google-chrome && \
        ln -sf /usr/bin/brave-browser /usr/bin/chromium; \
    else \
        echo "Error: Invalid BROWSER_TYPE='$BROWSER_TYPE'. Must be 'chrome' or 'brave'." && exit 1; \
    fi

# Copy and install Chrome/ChromeDriver depending on browser type
# For Chrome: use artifacts from builder stage
# For Brave: download ChromeDriver at runtime since Brave was installed from apt
RUN if [ "$BROWSER_TYPE" = "chrome" ]; then \
        echo "Installing Chrome from builder artifacts..."; \
    elif [ "$BROWSER_TYPE" = "brave" ]; then \
        echo "Installing ChromeDriver for Brave..."; \
        CHROMEDRIVER_VERSION=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE") && \
        curl -fsSL "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" -o /tmp/chromedriver.zip && \
        unzip -q /tmp/chromedriver.zip -d /tmp && \
        mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
        chmod +x /usr/local/bin/chromedriver && \
        rm -rf /tmp/chromedriver*; \
    fi

# For Chrome: Copy ChromeDriver from builder
COPY --from=builder /downloads/chromedriver-linux64/chromedriver /tmp/chromedriver-from-builder
RUN if [ "$BROWSER_TYPE" = "chrome" ] && [ -s /tmp/chromedriver-from-builder ]; then \
        mv /tmp/chromedriver-from-builder /usr/local/bin/chromedriver && \
        chmod +x /usr/local/bin/chromedriver; \
    else \
        rm -f /tmp/chromedriver-from-builder; \
    fi

# For Chrome: Copy and install Chrome .deb from builder
COPY --from=builder /downloads/google-chrome-stable_current_amd64.deb /tmp/chrome.deb
RUN if [ "$BROWSER_TYPE" = "chrome" ] && [ -s /tmp/chrome.deb ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends /tmp/chrome.deb && \
        rm -f /tmp/chrome.deb && \
        rm -rf /var/lib/apt/lists/*; \
    else \
        rm -f /tmp/chrome.deb; \
    fi

# Create non-root rpa user with sudo access for Chrome policy management
# The rpauser can write to /etc/opt/chrome/policies/managed/ via sudo (needed for certificate policies)
RUN useradd -m -d /app -u 1000 rpauser \
 && echo "rpauser ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Set up working directory structure
WORKDIR /app
RUN mkdir -p /app/src /app/logs /app/tmp /app/recordings \
    /app/.cache \
    /data \
    && chmod 1777 /app/tmp \
    && chmod 777 /data \
    && chmod 777 /app/recordings \
    && chown -R rpauser:rpauser /app

# =============================================================================
# A1 PERSONAL CERTIFICATE SUPPORT (RUNTIME MANAGEMENT)
# =============================================================================
# The NSS database for Chrome client certificates (.pfx/.p12) is managed at
# runtime by Python code, not pre-initialized here. This ensures:
#   1. Only ONE personal certificate exists at any time (single-cert policy)
#   2. Python can fully control the certificate lifecycle (import/rotate/remove)
#   3. Certificates are never baked into the image (security best practice)
#
# Runtime Python Flow:
#   - Receives .pfx file via API (never in image)
#   - Creates/resets ~/.pki/nssdb using: certutil -N -d sql:$HOME/.pki/nssdb --empty-password
#   - Imports certificate using: pk12util -i /tmp/cert.pfx -d sql:$HOME/.pki/nssdb -W <password> -n <nickname>
#   - Writes Chrome policy to /etc/opt/chrome/policies/managed/auto_select_certificate.json
#   - Starts Chrome via Selenium (--headless=new supported)
#   - Removes certificate after task: certutil -D -d sql:$HOME/.pki/nssdb -n <nickname>
#
# The directories are created with proper permissions but remain empty until runtime.
# =============================================================================

# Create .pki directory structure for NSS database (managed at runtime)
# Both /app/.pki (rpauser home) and /root/.pki are created to support running as either user
RUN mkdir -p /app/.pki /root/.pki \
    && chmod 700 /app/.pki /root/.pki \
    && chown rpauser:rpauser /app/.pki

# Create Chrome policy directory for AutoSelectCertificateForUrls
# Python will write JSON policy files here at runtime using sudo
RUN mkdir -p /etc/opt/chrome/policies/managed \
    && chmod 755 /etc/opt/chrome/policies/managed

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

# Install noVNC and websockify for browser-based VNC access (optional feature)
RUN mkdir -p /opt/novnc /opt/websockify \
    && git clone --depth 1 https://github.com/novnc/noVNC.git /opt/novnc \
    && git clone --depth 1 https://github.com/novnc/websockify.git /opt/websockify \
    && ln -s /opt/novnc/vnc.html /opt/novnc/index.html \
    && pip install --no-cache-dir numpy \
    && cd /opt/websockify && python setup.py install

# Copy application files
COPY . .

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh /app/script_downloader.py /app/smoke_test.py

# Environment variables for control (all optional; defaults to lightweight/headless)
ENV USE_XVFB=0 \
    USE_OPENBOX=0 \
    USE_VNC=0 \
    USE_NOVNC=0 \
    USE_PJEOFFICE=0 \
    USE_SCREEN_RECORDING=0 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    RECORDING_DIR=/app/recordings \
    XDG_CACHE_HOME=/app/.cache

# Run as root user (rpauser kept for compatibility but not used)
# USER rpauser

# Set up entrypoint for dynamic script execution with download support
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden)
CMD ["python", "--version"]
