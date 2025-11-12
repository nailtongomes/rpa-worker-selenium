# VNC with Caddy Reverse Proxy

This guide shows how to securely expose VNC through a Caddy reverse proxy with authentication.

## Why Use a Reverse Proxy?

The default VNC setup has no password protection. A reverse proxy adds:
- **Authentication**: Basic auth or other authentication methods
- **HTTPS/TLS**: Encrypted connections
- **Access control**: Restrict by IP, user, etc.
- **Centralized management**: Single entry point for multiple services

## Prerequisites

- Docker and Docker Compose installed
- Domain name pointing to your server (for HTTPS with Let's Encrypt)
- Or use localhost for testing

## Setup with Caddy

### Option 1: Quick Setup with Docker Compose (Recommended)

Create a `docker-compose.caddy.yml` file:

```yaml
version: '3.8'

services:
  # RPA Worker with VNC enabled
  rpa-worker-vnc:
    build: .
    image: rpa-worker-selenium:latest
    container_name: rpa-worker-vnc
    environment:
      - USE_XVFB=1
      - USE_VNC=1
      - SCREEN_WIDTH=1920
      - SCREEN_HEIGHT=1080
    volumes:
      - ./scripts:/app/src
      - ./recordings:/app/recordings
    # Don't expose VNC port directly - access through Caddy
    # ports:
    #   - "5900:5900"  # Commented out for security
    networks:
      - rpa-network
    command: python /app/example_vnc_debug.py

  # Caddy reverse proxy with websocket support for VNC
  caddy:
    image: caddy:2-alpine
    container_name: caddy-vnc-proxy
    ports:
      - "80:80"      # HTTP
      - "443:443"    # HTTPS
      - "5901:5901"  # VNC through Caddy (websocket)
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - rpa-network
    depends_on:
      - rpa-worker-vnc

  # noVNC web client (optional - browser-based VNC viewer)
  novnc:
    image: theasp/novnc:latest
    container_name: novnc-viewer
    environment:
      - DISPLAY_WIDTH=1920
      - DISPLAY_HEIGHT=1080
      - RUN_XTERM=no
    ports:
      - "8080:8080"
    networks:
      - rpa-network
    depends_on:
      - rpa-worker-vnc
    command: --vnc rpa-worker-vnc:5900

networks:
  rpa-network:
    driver: bridge

volumes:
  caddy_data:
  caddy_config:
```

### Option 2: Caddyfile Configuration

Create a `Caddyfile` in your project directory:

#### For Production (with HTTPS and domain)

```caddyfile
# VNC over websocket with authentication
vnc.yourdomain.com {
    # Enable automatic HTTPS with Let's Encrypt
    tls your-email@example.com

    # Basic authentication
    # Generate password hash: caddy hash-password
    basicauth {
        admin $2a$14$Zkx19XLiW6VYouLHR5NmfOFU0z2GTNmpkT/5qqR7hx2wghCy4WvKe
    }

    # Reverse proxy to VNC server
    reverse_proxy rpa-worker-vnc:5900 {
        # Enable websocket support
        header_up Upgrade {http.request.header.Upgrade}
        header_up Connection {http.request.header.Connection}
    }

    # Security headers
    header {
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
        X-XSS-Protection "1; mode=block"
    }

    # Logging
    log {
        output file /var/log/caddy/vnc.log
        level INFO
    }
}

# noVNC web interface (browser-based VNC client)
novnc.yourdomain.com {
    tls your-email@example.com

    # Basic authentication (same credentials as VNC)
    basicauth {
        admin $2a$14$Zkx19XLiW6VYouLHR5NmfOFU0z2GTNmpkT/5qqR7hx2wghCy4WvKe
    }

    reverse_proxy novnc:8080

    # Security headers
    header {
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
        X-XSS-Protection "1; mode=block"
    }
}
```

#### For Local Development (HTTP only)

```caddyfile
# Local development without HTTPS
:5901 {
    # Optional: Basic authentication for local testing
    # Comment out if not needed
    basicauth {
        admin JDJhJDE0JFpreDlYTGlXNlZZb3VMSFI1Tm1mT0ZVMHJ6R1ROSm1wvdC9CnFiUjdoeDJ3Z2hDeTRXdktl
    }

    # Reverse proxy to VNC server
    reverse_proxy rpa-worker-vnc:5900 {
        # Enable websocket support
        header_up Upgrade {http.request.header.Upgrade}
        header_up Connection {http.request.header.Connection}
    }
}

# noVNC web interface
:8080 {
    reverse_proxy novnc:8080
}
```

### Option 3: Minimal Caddyfile (No Authentication - Local Only)

```caddyfile
# WARNING: No authentication - use only on trusted local networks
:5901 {
    reverse_proxy rpa-worker-vnc:5900
}
```

## Usage Instructions

### 1. Generate Password Hash

For basic authentication, generate a password hash:

```bash
# Using Docker
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'your-password'

# Or install Caddy locally
caddy hash-password --plaintext 'your-password'
```

Copy the hash and paste it in the Caddyfile after the username.

### 2. Start Services

```bash
# Using the docker-compose file
docker-compose -f docker-compose.caddy.yml up -d

# Check logs
docker-compose -f docker-compose.caddy.yml logs -f
```

### 3. Connect to VNC

#### Option A: Browser-based (noVNC)

Open your browser:
```
https://novnc.yourdomain.com
# or for local: http://localhost:8080
```

Enter your credentials when prompted.

#### Option B: VNC Client

```bash
# Production with domain
vncviewer vnc.yourdomain.com:443

# Local development
vncviewer localhost:5901
```

When prompted for credentials, use the username and password you configured.

## Security Best Practices

### 1. Use HTTPS in Production

Always use HTTPS with a valid certificate in production:
- Caddy automatically handles Let's Encrypt certificates
- Use a real domain name pointing to your server
- Don't expose port 5900 directly

### 2. Strong Authentication

```bash
# Generate strong password hash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'ComplexP@ssw0rd!'
```

### 3. IP Whitelisting (Optional)

Add IP restrictions to your Caddyfile:

```caddyfile
vnc.yourdomain.com {
    # Only allow specific IPs
    @allowed {
        remote_ip 192.168.1.0/24 10.0.0.0/8
    }
    handle @allowed {
        reverse_proxy rpa-worker-vnc:5900
    }
    handle {
        abort
    }
}
```

### 4. Rate Limiting

Protect against brute force attacks:

```caddyfile
vnc.yourdomain.com {
    # Limit to 10 requests per minute per IP
    rate_limit {
        zone vnc_zone {
            key {remote_host}
            events 10
            window 1m
        }
    }
    
    basicauth {
        admin $2a$14$...
    }
    
    reverse_proxy rpa-worker-vnc:5900
}
```

## Troubleshooting

### Can't Connect Through Caddy

1. Check services are running:
```bash
docker-compose -f docker-compose.caddy.yml ps
```

2. Check Caddy logs:
```bash
docker-compose -f docker-compose.caddy.yml logs caddy
```

3. Verify VNC is accessible from Caddy:
```bash
docker-compose -f docker-compose.caddy.yml exec caddy wget -O- http://rpa-worker-vnc:5900
```

### Certificate Issues (Production)

1. Verify DNS is pointing to your server:
```bash
dig vnc.yourdomain.com
```

2. Check ports 80 and 443 are open:
```bash
sudo netstat -tlnp | grep -E ':80|:443'
```

3. Check Caddy logs for certificate errors:
```bash
docker-compose -f docker-compose.caddy.yml logs caddy | grep -i certificate
```

### Authentication Not Working

1. Verify password hash is correctly formatted in Caddyfile
2. Test password generation:
```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'test123'
```
3. Check Caddy config syntax:
```bash
docker-compose -f docker-compose.caddy.yml exec caddy caddy validate --config /etc/caddy/Caddyfile
```

## Advanced Configuration

### Multiple VNC Services

Expose multiple RPA workers through different paths:

```caddyfile
vnc.yourdomain.com {
    tls your-email@example.com
    
    basicauth {
        admin $2a$14$...
    }

    # Worker 1
    handle /worker1* {
        uri strip_prefix /worker1
        reverse_proxy rpa-worker-vnc-1:5900
    }

    # Worker 2
    handle /worker2* {
        uri strip_prefix /worker2
        reverse_proxy rpa-worker-vnc-2:5900
    }
}
```

### Custom Authentication (JWT, OAuth, etc.)

For advanced authentication, use Caddy plugins or an authentication service:

```caddyfile
vnc.yourdomain.com {
    # Forward auth to external service
    forward_auth auth-service:9091 {
        uri /verify
        copy_headers X-User-Email
    }
    
    reverse_proxy rpa-worker-vnc:5900
}
```

### Monitoring and Metrics

Add Prometheus metrics:

```caddyfile
{
    servers {
        metrics
    }
}

:2019 {
    metrics /metrics
}

vnc.yourdomain.com {
    # ... your config
}
```

Access metrics at `http://localhost:2019/metrics`

## Example: Complete Production Setup

Here's a complete production-ready example:

**docker-compose.caddy.yml:**
```yaml
version: '3.8'

services:
  rpa-worker-vnc:
    build: .
    image: rpa-worker-selenium:latest
    environment:
      - USE_XVFB=1
      - USE_VNC=1
      - SCREEN_WIDTH=1920
      - SCREEN_HEIGHT=1080
    volumes:
      - ./scripts:/app/src
    networks:
      - rpa-network
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
      - ./logs/caddy:/var/log/caddy
    networks:
      - rpa-network
    restart: unless-stopped
    depends_on:
      - rpa-worker-vnc

  novnc:
    image: theasp/novnc:latest
    environment:
      - DISPLAY_WIDTH=1920
      - DISPLAY_HEIGHT=1080
      - RUN_XTERM=no
    networks:
      - rpa-network
    restart: unless-stopped
    command: --vnc rpa-worker-vnc:5900

networks:
  rpa-network:
    driver: bridge

volumes:
  caddy_data:
  caddy_config:
```

**Caddyfile:**
```caddyfile
{
    email your-email@example.com
}

vnc.yourdomain.com {
    basicauth {
        admin $2a$14$Zkx19XLiW6VYouLHR5NmfOFU0z2GTNmpkT/5qqR7hx2wghCy4WvKe
    }

    reverse_proxy rpa-worker-vnc:5900 {
        header_up Upgrade {http.request.header.Upgrade}
        header_up Connection {http.request.header.Connection}
    }

    header {
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
        Strict-Transport-Security "max-age=31536000;"
    }

    log {
        output file /var/log/caddy/vnc.log
    }
}

novnc.yourdomain.com {
    basicauth {
        admin $2a$14$Zkx19XLiW6VYouLHR5NmfOFU0z2GTNmpkT/5qqR7hx2wghCy4WvKe
    }

    reverse_proxy novnc:8080

    header {
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
        Strict-Transport-Security "max-age=31536000;"
    }

    log {
        output file /var/log/caddy/novnc.log
    }
}
```

**Start the stack:**
```bash
docker-compose -f docker-compose.caddy.yml up -d
```

**Access:**
- Browser VNC: https://novnc.yourdomain.com
- VNC client: vncviewer vnc.yourdomain.com:443

## Additional Resources

- [Caddy Documentation](https://caddyserver.com/docs/)
- [noVNC GitHub](https://github.com/novnc/noVNC)
- [Let's Encrypt](https://letsencrypt.org/)
- Main VNC documentation: [VNC_QUICKSTART.md](VNC_QUICKSTART.md)
