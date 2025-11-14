# Runtime CA Certificate Management Guide

This guide explains how to install, list, and remove CA certificates at runtime in the rpa-worker-selenium Docker containers.

## Overview

All rpa-worker-selenium images include the `ca-certificates` package and related tools, allowing Python scripts to manage system-wide CA certificates dynamically at runtime. This is essential for systems that require authentication with custom Certificate Authorities (CA).

## Available Tools

The following tools are pre-installed in all images:

- **ca-certificates** - System CA certificates management
- **openssl** - SSL/TLS toolkit for certificate operations
- **libnss3-tools** - NSS certificate database management (certutil, pk12util)
- **update-ca-certificates** - Update system CA trust store

## Use Cases

### 1. Installing CA Certificates at Runtime

You can install custom CA certificates at runtime by copying them to the system trust store and updating the certificate database.

**Python Example:**

```python
import subprocess
import shutil
from pathlib import Path

def install_ca_certificate(cert_path: str, cert_name: str):
    """
    Install a CA certificate at runtime.
    
    Args:
        cert_path: Path to the .crt or .pem certificate file
        cert_name: Name for the certificate (without extension)
    """
    # Copy certificate to system CA directory
    dest_path = f"/usr/local/share/ca-certificates/{cert_name}.crt"
    shutil.copy(cert_path, dest_path)
    
    # Update CA certificates
    subprocess.run(["update-ca-certificates"], check=True)
    
    print(f"✅ CA certificate '{cert_name}' installed successfully")

# Usage
install_ca_certificate("/path/to/custom-ca.crt", "my-custom-ca")
```

**Bash Example:**

```bash
# Copy the certificate to the system CA directory
cp /path/to/custom-ca.crt /usr/local/share/ca-certificates/my-custom-ca.crt

# Update the system CA trust store
update-ca-certificates

# Verify installation
ls -l /etc/ssl/certs/ | grep my-custom-ca
```

### 2. Listing Installed CA Certificates

**Python Example:**

```python
import subprocess

def list_ca_certificates():
    """List all installed CA certificates."""
    result = subprocess.run(
        ["ls", "-l", "/etc/ssl/certs/"],
        capture_output=True,
        text=True
    )
    print("Installed CA certificates:")
    print(result.stdout)
    return result.stdout

# Usage
list_ca_certificates()
```

**Bash Example:**

```bash
# List all CA certificates
ls -l /etc/ssl/certs/

# Count CA certificates
ls -1 /etc/ssl/certs/*.pem | wc -l

# Search for specific CA
ls -l /etc/ssl/certs/ | grep -i "my-custom-ca"
```

### 3. Removing CA Certificates

**Python Example:**

```python
import subprocess
from pathlib import Path

def remove_ca_certificate(cert_name: str):
    """
    Remove a CA certificate at runtime.
    
    Args:
        cert_name: Name of the certificate (without extension)
    """
    cert_path = Path(f"/usr/local/share/ca-certificates/{cert_name}.crt")
    
    if cert_path.exists():
        cert_path.unlink()
        
        # Update CA certificates to remove from trust store
        subprocess.run(["update-ca-certificates", "--fresh"], check=True)
        
        print(f"✅ CA certificate '{cert_name}' removed successfully")
    else:
        print(f"⚠️  Certificate '{cert_name}' not found")

# Usage
remove_ca_certificate("my-custom-ca")
```

**Bash Example:**

```bash
# Remove the certificate file
rm /usr/local/share/ca-certificates/my-custom-ca.crt

# Update the system CA trust store
update-ca-certificates --fresh

# Verify removal
ls -l /etc/ssl/certs/ | grep my-custom-ca
```

### 4. Managing NSS Certificate Database (for Browsers)

For browser-specific certificates (Chrome, Firefox, Brave), use the NSS tools:

**Python Example:**

```python
import subprocess
import os

def install_nss_ca_certificate(cert_path: str, cert_name: str, nssdb_path: str = None):
    """
    Install a CA certificate into NSS database for browsers.
    
    Args:
        cert_path: Path to the .crt or .pem certificate file
        cert_name: Nickname for the certificate
        nssdb_path: Path to NSS database (default: ~/.pki/nssdb)
    """
    if nssdb_path is None:
        home = os.environ.get('HOME', '/app')
        nssdb_path = f"sql:{home}/.pki/nssdb"
    
    # Import CA certificate into NSS database
    subprocess.run([
        "certutil", "-A",
        "-d", nssdb_path,
        "-n", cert_name,
        "-t", "CT,C,C",  # Trust flags for CA
        "-i", cert_path
    ], check=True)
    
    print(f"✅ NSS CA certificate '{cert_name}' installed successfully")

def list_nss_certificates(nssdb_path: str = None):
    """List certificates in NSS database."""
    if nssdb_path is None:
        home = os.environ.get('HOME', '/app')
        nssdb_path = f"sql:{home}/.pki/nssdb"
    
    result = subprocess.run(
        ["certutil", "-L", "-d", nssdb_path],
        capture_output=True,
        text=True
    )
    print("NSS Certificates:")
    print(result.stdout)
    return result.stdout

def remove_nss_certificate(cert_name: str, nssdb_path: str = None):
    """Remove a certificate from NSS database."""
    if nssdb_path is None:
        home = os.environ.get('HOME', '/app')
        nssdb_path = f"sql:{home}/.pki/nssdb"
    
    subprocess.run([
        "certutil", "-D",
        "-d", nssdb_path,
        "-n", cert_name
    ], check=True)
    
    print(f"✅ NSS certificate '{cert_name}' removed successfully")

# Usage
install_nss_ca_certificate("/path/to/ca.crt", "MyCustomCA")
list_nss_certificates()
remove_nss_certificate("MyCustomCA")
```

## Docker Container Usage

### Mount CA Certificates at Runtime

```bash
# Mount CA certificate directory
docker run --rm \
  -v /path/to/ca-certs:/tmp/ca-certs:ro \
  rpa-worker-selenium \
  bash -c "
    cp /tmp/ca-certs/*.crt /usr/local/share/ca-certificates/ && \
    update-ca-certificates && \
    python your_script.py
  "
```

### Use Environment Variable for Certificate Path

```bash
docker run --rm \
  -e CA_CERT_PATH=/tmp/ca-certs/custom-ca.crt \
  -v /path/to/ca-certs:/tmp/ca-certs:ro \
  rpa-worker-selenium \
  python script_that_installs_ca.py
```

## Complete Python Script Example

```python
#!/usr/bin/env python3
"""
Complete example for runtime CA certificate management.
"""

import os
import subprocess
import shutil
from pathlib import Path

class CACertificateManager:
    """Manage system CA certificates at runtime."""
    
    def __init__(self):
        self.ca_dir = Path("/usr/local/share/ca-certificates")
        self.ca_dir.mkdir(parents=True, exist_ok=True)
    
    def install(self, cert_path: str, cert_name: str = None):
        """Install a CA certificate."""
        cert_path = Path(cert_path)
        
        if not cert_path.exists():
            raise FileNotFoundError(f"Certificate not found: {cert_path}")
        
        if cert_name is None:
            cert_name = cert_path.stem
        
        # Ensure .crt extension
        if not cert_name.endswith('.crt'):
            cert_name += '.crt'
        
        dest_path = self.ca_dir / cert_name
        shutil.copy(cert_path, dest_path)
        
        # Update system CA trust store
        result = subprocess.run(
            ["update-ca-certificates"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ CA certificate '{cert_name}' installed")
            print(f"   Location: {dest_path}")
        else:
            print(f"❌ Failed to install CA certificate")
            print(result.stderr)
            raise RuntimeError("Certificate installation failed")
    
    def list(self):
        """List installed custom CA certificates."""
        certs = list(self.ca_dir.glob("*.crt"))
        
        if not certs:
            print("No custom CA certificates installed")
            return []
        
        print(f"Custom CA certificates ({len(certs)}):")
        for cert in certs:
            print(f"  - {cert.name}")
        
        return [cert.name for cert in certs]
    
    def remove(self, cert_name: str):
        """Remove a CA certificate."""
        if not cert_name.endswith('.crt'):
            cert_name += '.crt'
        
        cert_path = self.ca_dir / cert_name
        
        if not cert_path.exists():
            print(f"⚠️  Certificate '{cert_name}' not found")
            return False
        
        cert_path.unlink()
        
        # Rebuild CA trust store
        result = subprocess.run(
            ["update-ca-certificates", "--fresh"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ CA certificate '{cert_name}' removed")
            return True
        else:
            print(f"❌ Failed to remove CA certificate")
            print(result.stderr)
            return False
    
    def verify_certificate(self, cert_path: str):
        """Verify a certificate file."""
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-text", "-noout"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ Certificate is valid")
            print(result.stdout)
            return True
        else:
            print(f"❌ Invalid certificate")
            print(result.stderr)
            return False

def main():
    """Example usage."""
    manager = CACertificateManager()
    
    # Example: Install CA from environment variable
    ca_cert_path = os.environ.get('CA_CERT_PATH')
    
    if ca_cert_path:
        print(f"Installing CA certificate from: {ca_cert_path}")
        manager.verify_certificate(ca_cert_path)
        manager.install(ca_cert_path)
    
    # List installed certificates
    manager.list()
    
    # Your application code here
    print("\n🚀 Application running with custom CA certificates")
    
    # Clean up (optional)
    # manager.remove("my-custom-ca")

if __name__ == "__main__":
    main()
```

## Important Notes

1. **Permissions**: Installing system CA certificates requires root access (default in containers)
2. **Security**: Never commit CA certificates into the Docker image
3. **Runtime**: Always install CA certificates at container startup before running your scripts
4. **NSS Database**: For browser automation, you may need both system CA and NSS database certificates
5. **Verification**: Always verify certificate validity before installation using `openssl x509`

## Troubleshooting

### SSL Certificate Verification Failed

If you get SSL errors after installing a CA:

```bash
# Rebuild the CA certificate bundle
update-ca-certificates --fresh

# Verify the certificate is in the system trust store
ls -l /etc/ssl/certs/ | grep your-ca-name

# Test HTTPS connection
openssl s_client -connect your-server.com:443 -CApath /etc/ssl/certs/
```

### Browser Not Recognizing CA Certificate

For Chrome/Brave browsers, you may need to install the CA in both system store and NSS database:

```python
# Install in system store
manager.install("/path/to/ca.crt", "my-ca")

# Also install in NSS database for browsers
subprocess.run([
    "certutil", "-A",
    "-d", "sql:/app/.pki/nssdb",
    "-n", "my-ca",
    "-t", "CT,C,C",
    "-i", "/path/to/ca.crt"
], check=True)
```

## See Also

- [A1 Certificate Management Guide](A1_CERTIFICATE_GUIDE.md) - For personal certificates (.pfx/.p12)
- [example_cert_management.py](example_cert_management.py) - Personal certificate management example
- Official [ca-certificates documentation](https://manpages.debian.org/bookworm/ca-certificates/update-ca-certificates.8.en.html)
