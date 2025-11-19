# A1 Personal Certificate Support

This document explains how to use the A1 personal certificate (.pfx/.p12) management feature in the RPA Worker Selenium Docker image. This feature is specifically designed for scenarios where Chrome needs to authenticate using client certificates, such as:

- Brazilian A1 digital certificates (e-CPF, e-CNPJ)
- Corporate client authentication certificates
- Government portal authentication
- Any system requiring mutual TLS authentication

## Overview

The Docker image is configured to support **runtime management** of personal certificates with the following guarantees:

1. ✅ **Single Certificate Policy**: Only ONE personal certificate exists at any time
2. ✅ **Full Lifecycle Control**: Python code has complete control over certificate import, rotation, and removal
3. ✅ **Security**: No certificates are baked into the Docker image
4. ✅ **Headless Support**: Works in both visual and `--headless=new` Chrome modes
5. ✅ **Auto-Selection**: Chrome automatically uses the certificate without prompts

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Python Service (receives .pfx via API)                     │
│  ↓                                                           │
│  1. Create/Reset NSS Database (~/.pki/nssdb)                │
│  2. Import .pfx Certificate                                 │
│  3. Write Chrome Policy (AutoSelectCertificateForUrls)      │
│  4. Start Chrome via Selenium                               │
│  5. Perform Automation                                      │
│  6. Remove Certificate                                      │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

- **NSS Database**: Chrome's certificate store at `~/.pki/nssdb`
- **Chrome Policy**: Auto-selection policy at `/etc/opt/chrome/policies/managed/auto_select_certificate.json`
- **Tools Installed**: `certutil`, `pk12util`, `openssl`
- **Users**: Both `root` and `rpauser` (UID 1000) can manage certificates

## Prerequisites

The following packages are pre-installed in the Docker image:

- `libnss3` - NSS library
- `libnss3-tools` - Certificate management tools (certutil, pk12util)
- `ca-certificates` - Root CA certificates
- `openssl` - SSL/TLS toolkit

The Chrome policy directory (`/etc/opt/chrome/policies/managed`) is owned by `rpauser`, allowing direct write access without sudo.

## Quick Start

### 1. Basic Usage with Certificate

```bash
# Mount your certificate file and run automation
docker run --rm \
  -v /path/to/your/certificate.pfx:/tmp/cert.pfx:ro \
  -e PFX_PASSWORD="your_password" \
  rpa-worker-selenium \
  python your_automation_script.py
```

### 2. Example Python Script

See `example_cert_management.py` for a complete working example. Here's the essential flow:

```python
import subprocess
import json
import tempfile
from pathlib import Path

HOME = "/app"  # or "/root" if running as root
NSS_DB_PATH = f"sql:{HOME}/.pki/nssdb"
CHROME_POLICY_FILE = "/etc/opt/chrome/policies/managed/auto_select_certificate.json"

# Step 1: Initialize NSS database
def initialize_nss_database():
    # Remove existing database for clean state
    nssdb_dir = Path(HOME) / ".pki" / "nssdb"
    if nssdb_dir.exists():
        import shutil
        shutil.rmtree(nssdb_dir)
    
    # Create new database
    nssdb_dir.parent.mkdir(parents=True, exist_ok=True)
    nssdb_dir.mkdir(exist_ok=True)
    nssdb_dir.chmod(0o700)
    
    subprocess.run([
        "certutil", "-N", "-d", NSS_DB_PATH, "--empty-password"
    ], check=True)

# Step 2: Import certificate
def import_certificate(pfx_path, pfx_password, nickname="client_cert"):
    subprocess.run([
        "pk12util", "-i", pfx_path,
        "-d", NSS_DB_PATH,
        "-W", pfx_password,
        "-n", nickname
    ], check=True)

# Step 3: Configure Chrome policy for auto-selection
def write_chrome_policy(pattern="*"):
    policy = {
        "AutoSelectCertificateForUrls": [
            json.dumps({"pattern": pattern, "filter": {}})
        ]
    }
    
    # Write policy directly (no sudo needed when running as rpauser)
    with open(CHROME_POLICY_FILE, 'w') as f:
        json.dump(policy, f, indent=2)
    
    os.chmod(CHROME_POLICY_FILE, 0o644)

# Step 4: Use with Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

chrome_options = Options()
chrome_options.add_argument('--headless=new')  # or remove for visual mode
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=chrome_options)
driver.get("https://your-site-requiring-certificate.com")
# Chrome automatically uses the certificate!

# Step 5: Cleanup after task
def remove_certificate(nickname="client_cert"):
    subprocess.run([
        "certutil", "-D", "-d", NSS_DB_PATH, "-n", nickname
    ], check=True)
    # Remove policy file directly (no sudo needed when running as rpauser)
    try:
        os.remove(CHROME_POLICY_FILE)
    except FileNotFoundError:
        pass

# Always cleanup!
remove_certificate()
driver.quit()
```

## Certificate Management Commands

### Initialize NSS Database

```bash
# Create new database with empty password
certutil -N -d sql:$HOME/.pki/nssdb --empty-password
```

### Import Certificate

```bash
# Import .pfx file into NSS database
pk12util -i /tmp/cert.pfx \
  -d sql:$HOME/.pki/nssdb \
  -W "certificate_password" \
  -n "my_cert_nickname"
```

### List Certificates

```bash
# List all certificates in database
certutil -L -d sql:$HOME/.pki/nssdb

# List with details
certutil -L -d sql:$HOME/.pki/nssdb -n "my_cert_nickname"
```

### Remove Certificate

```bash
# Delete certificate by nickname
certutil -D -d sql:$HOME/.pki/nssdb -n "my_cert_nickname"
```

### Verify Certificate

```bash
# Verify certificate validity
certutil -V -u C -d sql:$HOME/.pki/nssdb -n "my_cert_nickname"
```

## Chrome Policy Configuration

Chrome uses the `AutoSelectCertificateForUrls` policy for automatic certificate selection. This policy must be written to:

```
/etc/opt/chrome/policies/managed/auto_select_certificate.json
```

### Basic Policy (Wildcard)

```json
{
  "AutoSelectCertificateForUrls": [
    "{\"pattern\":\"*\",\"filter\":{}}"
  ]
}
```

This matches ALL URLs and automatically selects the certificate (works because we maintain a single-certificate policy).

### Filtered Policy (Specific URL Pattern)

```json
{
  "AutoSelectCertificateForUrls": [
    "{\"pattern\":\"https://[*.]example.com\",\"filter\":{}}"
  ]
}
```

### Filtered by Issuer/Subject

```json
{
  "AutoSelectCertificateForUrls": [
    "{\"pattern\":\"*\",\"filter\":{\"ISSUER\":{\"CN\":\"Certificate Authority Name\"}}}"
  ]
}
```

For more details, see [Chrome Enterprise Policy Documentation](https://chromeenterprise.google/policies/#AutoSelectCertificateForUrls).

## Running as Different Users

### As Root (Default)

```bash
docker run --rm -v /path/to/cert.pfx:/tmp/cert.pfx:ro \
  rpa-worker-selenium python script.py
```

Uses NSS database at `/root/.pki/nssdb`.

### As rpauser (Non-root)

```bash
docker run --rm --user rpauser \
  -v /path/to/cert.pfx:/tmp/cert.pfx:ro \
  rpa-worker-selenium python script.py
```

Uses NSS database at `/app/.pki/nssdb` (HOME=/app for rpauser).

## Security Best Practices

### ✅ DO

- **Receive certificates via API** at runtime, never commit to Git
- **Store passwords in secure vaults** (HashiCorp Vault, AWS Secrets Manager, etc.)
- **Delete certificates immediately** after task completion
- **Use read-only mounts** when mounting certificate files (`-v path:/tmp/cert.pfx:ro`)
- **Rotate certificates regularly** as part of your security policy
- **Log certificate operations** for audit trails
- **Validate certificate expiry** before use

### ❌ DON'T

- ❌ Commit `.pfx` files to Git repositories
- ❌ Include certificates in Docker image layers
- ❌ Hard-code certificate passwords in scripts
- ❌ Leave certificates in NSS database after task completion
- ❌ Reuse the same certificate for multiple concurrent tasks without isolation
- ❌ Expose certificate files in logs or error messages

## Example: Complete Automation Flow

```python
#!/usr/bin/env python3
"""
Complete A1 certificate automation example
"""
import os
import subprocess
import json
import tempfile
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Configuration
HOME = os.environ.get('HOME', '/app')
NSS_DB_PATH = f"sql:{HOME}/.pki/nssdb"
CHROME_POLICY_FILE = "/etc/opt/chrome/policies/managed/auto_select_certificate.json"

def setup_certificate(pfx_path, pfx_password, nickname="client_cert"):
    """Complete certificate setup"""
    print("Setting up certificate...")
    
    # 1. Initialize NSS database
    nssdb_dir = Path(HOME) / ".pki" / "nssdb"
    if nssdb_dir.exists():
        import shutil
        shutil.rmtree(nssdb_dir)
    
    nssdb_dir.parent.mkdir(parents=True, exist_ok=True)
    nssdb_dir.mkdir(exist_ok=True)
    nssdb_dir.chmod(0o700)
    
    subprocess.run([
        "certutil", "-N", "-d", NSS_DB_PATH, "--empty-password"
    ], check=True)
    
    # 2. Import certificate
    subprocess.run([
        "pk12util", "-i", pfx_path,
        "-d", NSS_DB_PATH,
        "-W", pfx_password,
        "-n", nickname
    ], check=True)
    
    # 3. Write Chrome policy (direct write, no sudo needed when running as rpauser)
    policy = {
        "AutoSelectCertificateForUrls": [
            json.dumps({"pattern": "*", "filter": {}})
        ]
    }
    
    with open(CHROME_POLICY_FILE, 'w') as f:
        json.dump(policy, f, indent=2)
    
    os.chmod(CHROME_POLICY_FILE, 0o644)
    
    print("Certificate setup complete!")

def cleanup_certificate(nickname="client_cert"):
    """Remove certificate and policy"""
    subprocess.run([
        "certutil", "-D", "-d", NSS_DB_PATH, "-n", nickname
    ], check=False)
    # Remove policy file directly (no sudo needed when running as rpauser)
    try:
        os.remove(CHROME_POLICY_FILE)
    except FileNotFoundError:
        pass
    print("Certificate cleaned up!")

def main():
    # Get certificate info from environment
    pfx_path = os.environ.get('PFX_PATH', '/tmp/cert.pfx')
    pfx_password = os.environ.get('PFX_PASSWORD', '')
    
    if not Path(pfx_path).exists():
        print(f"Error: Certificate not found at {pfx_path}")
        return 1
    
    try:
        # Setup certificate
        setup_certificate(pfx_path, pfx_password)
        
        # Configure Chrome
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        service = Service('/usr/local/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Your automation here
        driver.get("https://your-site.com")
        print(f"Page title: {driver.title}")
        
        # Cleanup
        driver.quit()
        cleanup_certificate()
        
        print("Automation completed successfully!")
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        cleanup_certificate()
        return 1

if __name__ == "__main__":
    exit(main())
```

Run with:

```bash
docker run --rm \
  -v /path/to/cert.pfx:/tmp/cert.pfx:ro \
  -e PFX_PASSWORD="your_password" \
  rpa-worker-selenium \
  python your_script.py
```

## Troubleshooting

### Certificate not being used by Chrome

1. Verify certificate is imported:
   ```bash
   certutil -L -d sql:$HOME/.pki/nssdb
   ```

2. Check Chrome policy exists:
   ```bash
   cat /etc/opt/chrome/policies/managed/auto_select_certificate.json
   ```

3. Verify policy permissions:
   ```bash
   ls -l /etc/opt/chrome/policies/managed/
   ```

### "SEC_ERROR_BAD_DATABASE" error

This usually means the NSS database directory doesn't exist or has wrong permissions:

```bash
mkdir -p $HOME/.pki/nssdb
chmod 700 $HOME/.pki/nssdb
certutil -N -d sql:$HOME/.pki/nssdb --empty-password
```

### Certificate import fails

1. Verify .pfx file is readable:
   ```bash
   file /tmp/cert.pfx
   ```

2. Test password with openssl:
   ```bash
   openssl pkcs12 -in /tmp/cert.pfx -noout -passin pass:yourpassword
   ```

### Chrome doesn't use certificate in headless mode

Make sure you're using `--headless=new` (not old `--headless`):

```python
chrome_options.add_argument('--headless=new')
```

## Advanced: Multiple Certificates

If you need to switch between multiple certificates (e.g., for different users or tasks), follow this pattern:

```python
def switch_certificate(old_nickname, new_pfx_path, new_password, new_nickname):
    # 1. Remove old certificate
    subprocess.run(["certutil", "-D", "-d", NSS_DB_PATH, "-n", old_nickname])
    
    # 2. Import new certificate
    subprocess.run([
        "pk12util", "-i", new_pfx_path,
        "-d", NSS_DB_PATH,
        "-W", new_password,
        "-n", new_nickname
    ])
    
    # Policy remains the same (wildcard matches any certificate)
```

## Additional Resources

- [NSS Tools Documentation](https://firefox-source-docs.mozilla.org/security/nss/tools/index.html)
- [Chrome Enterprise Policy List](https://chromeenterprise.google/policies/)
- [PKCS#12 Format Specification](https://datatracker.ietf.org/doc/html/rfc7292)

## Support

For issues specific to certificate management:
- Check the example script: `example_cert_management.py`
- Review Chrome logs: Add `chrome_options.add_argument('--enable-logging')` 
- Test certificate manually with `certutil` commands

For general issues, see the main [README.md](README.md).
