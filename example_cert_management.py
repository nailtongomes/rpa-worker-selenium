#!/usr/bin/env python3
"""
Example: A1 Personal Certificate Management for Chrome

This example demonstrates the runtime flow for managing A1 personal certificates
(.pfx/.p12 files) with Chrome's NSS database. This approach ensures:
  1. Only ONE personal certificate is present at any time
  2. Full control over certificate lifecycle (import/rotate/remove)
  3. No certificates baked into the Docker image (security best practice)

Requirements:
  - Container must be built from Dockerfile or Dockerfile.chrome
  - Required tools: certutil, pk12util (pre-installed in image)
  - Sudo access for writing Chrome policies (already configured)

Usage:
  docker run --rm -v /path/to/cert.pfx:/tmp/cert.pfx:ro \\
    rpa-worker-selenium example_cert_management.py

Author: RPA Worker Selenium Team
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path

# Configuration
HOME = os.environ.get('HOME', '/app')
NSS_DB_PATH = f"sql:{HOME}/.pki/nssdb"
CHROME_POLICY_DIR = "/etc/opt/chrome/policies/managed"
CHROME_POLICY_FILE = f"{CHROME_POLICY_DIR}/auto_select_certificate.json"


def run_command(cmd, check=True):
    """Execute a shell command and return the result."""
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  ❌ Command failed with exit code {result.returncode}")
        print(f"  stderr: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def initialize_nss_database():
    """
    Create or reset the NSS database for certificate storage.
    
    This ensures a clean state with no existing certificates.
    Python has full control over the database lifecycle.
    """
    print("\n[1] Initializing NSS database...")
    
    nssdb_dir = Path(HOME) / ".pki" / "nssdb"
    
    # Remove existing database if present (ensures single certificate policy)
    if nssdb_dir.exists():
        print(f"  Removing existing NSS database at {nssdb_dir}")
        import shutil
        shutil.rmtree(nssdb_dir)
    
    # Create parent directory if needed
    nssdb_dir.parent.mkdir(parents=True, exist_ok=True)
    nssdb_dir.parent.chmod(0o700)
    
    # Create the nssdb directory
    nssdb_dir.mkdir(exist_ok=True)
    nssdb_dir.chmod(0o700)
    
    # Initialize new database with empty password
    try:
        run_command(["certutil", "-N", "-d", NSS_DB_PATH, "--empty-password"])
        print(f"  ✅ NSS database initialized at {nssdb_dir}")
    except subprocess.CalledProcessError as e:
        # Check if this is because we're not in the container environment
        if "SEC_ERROR_BAD_DATABASE" in e.stderr or "security library" in e.stderr:
            print(f"  ⚠️  NSS database initialization failed")
            print(f"      This is expected when running outside the container")
            print(f"      Inside the container, this would succeed")
            raise RuntimeError("Not running in container environment") from e
        else:
            raise


def import_pfx_certificate(pfx_path, pfx_password, nickname="client_cert"):
    """
    Import a .pfx certificate into the NSS database.
    
    Args:
        pfx_path: Path to the .pfx file
        pfx_password: Password for the .pfx file
        nickname: Certificate nickname in NSS database
    """
    print(f"\n[2] Importing certificate from {pfx_path}...")
    
    if not Path(pfx_path).exists():
        raise FileNotFoundError(f"Certificate file not found: {pfx_path}")
    
    # Import certificate using pk12util
    # The -W flag specifies the password for the .pfx file
    run_command([
        "pk12util", "-i", pfx_path,
        "-d", NSS_DB_PATH,
        "-W", pfx_password,
        "-n", nickname
    ])
    
    print(f"  ✅ Certificate imported with nickname: {nickname}")


def list_certificates():
    """List all certificates in the NSS database."""
    print("\n[3] Listing certificates in NSS database...")
    
    result = run_command(["certutil", "-L", "-d", NSS_DB_PATH], check=False)
    print(result.stdout)
    
    # Count personal certificates (those with 'u' flag in Trust Attributes)
    lines = result.stdout.strip().split('\n')[2:]  # Skip header lines
    personal_certs = [line for line in lines if line and 'u' in line.split()[-1]]
    
    print(f"  Personal certificates found: {len(personal_certs)}")
    return personal_certs


def write_chrome_policy(pattern="*", issuer_cn=None, subject_cn=None):
    """
    Write Chrome policy for automatic client certificate selection.
    
    Args:
        pattern: URL pattern for auto-selection (default: "*" matches all URLs)
        issuer_cn: Optional issuer CN filter
        subject_cn: Optional subject CN filter
    """
    print("\n[4] Writing Chrome policy for auto certificate selection...")
    
    # Build filter object
    filter_obj = {}
    if issuer_cn:
        filter_obj["ISSUER"] = {"CN": issuer_cn}
    if subject_cn:
        filter_obj["SUBJECT"] = {"CN": subject_cn}
    
    # Create policy
    policy = {
        "AutoSelectCertificateForUrls": [
            json.dumps({"pattern": pattern, "filter": filter_obj})
        ]
    }
    
    # Write policy file directly (no sudo needed when running as rpauser)
    # The /etc/opt/chrome/policies/managed directory is owned by rpauser
    policy_json = json.dumps(policy, indent=2)
    
    try:
        with open(CHROME_POLICY_FILE, 'w') as f:
            f.write(policy_json)
        
        os.chmod(CHROME_POLICY_FILE, 0o644)
        print(f"  ✅ Chrome policy written to {CHROME_POLICY_FILE}")
        print(f"  Policy: {policy}")
    except PermissionError as e:
        print(f"  ❌ Permission denied writing policy file: {e}")
        print(f"  Note: Running as root? Directory ownership may need adjustment.")
        raise


def remove_certificate(nickname="client_cert"):
    """
    Remove a certificate from the NSS database.
    
    This should be called after completing the automation task
    to maintain the "single certificate" policy.
    
    Args:
        nickname: Certificate nickname to remove
    """
    print(f"\n[5] Removing certificate '{nickname}' from NSS database...")
    
    result = run_command(["certutil", "-D", "-d", NSS_DB_PATH, "-n", nickname], check=False)
    
    if result.returncode == 0:
        print(f"  ✅ Certificate '{nickname}' removed successfully")
    else:
        print(f"  ⚠️  Certificate '{nickname}' not found or already removed")


def cleanup_chrome_policy():
    """Remove Chrome policy file."""
    print("\n[6] Cleaning up Chrome policy...")
    
    try:
        os.remove(CHROME_POLICY_FILE)
        print("  ✅ Chrome policy cleaned up")
    except FileNotFoundError:
        print("  ℹ️  Policy file not found (already cleaned up)")
    except PermissionError as e:
        print(f"  ⚠️  Permission denied removing policy file: {e}")


def check_prerequisites():
    """Check if required tools are available."""
    required_tools = ["certutil", "pk12util"]
    missing_tools = []
    
    for tool in required_tools:
        result = subprocess.run(["which", tool], capture_output=True)
        if result.returncode != 0:
            missing_tools.append(tool)
    
    if missing_tools:
        print("\n⚠️  Missing required tools:")
        for tool in missing_tools:
            print(f"    - {tool}")
        print("\nThis script must be run inside the Docker container where")
        print("libnss3-tools is installed. Required tools: certutil, pk12util")
        print("\nTo run this example:")
        print("  docker run --rm rpa-worker-selenium python example_cert_management.py")
        return False
    return True


def main():
    """Main demonstration of certificate management flow."""
    print("=" * 70)
    print("A1 Personal Certificate Management - Example Flow")
    print("=" * 70)
    
    # Check prerequisites
    if not check_prerequisites():
        return 1
    
    # For this example, we'll use a dummy certificate path
    # In production, this would come from an API or secure volume
    cert_path = "/tmp/cert.pfx"
    cert_password = "password123"  # Would come from secure source in production
    cert_nickname = "my_client_cert"
    
    print(f"\nConfiguration:")
    print(f"  HOME: {HOME}")
    print(f"  NSS DB: {NSS_DB_PATH}")
    print(f"  Chrome Policy: {CHROME_POLICY_FILE}")
    print(f"  Certificate: {cert_path}")
    
    try:
        # Step 1: Initialize/Reset NSS database
        initialize_nss_database()
        
        # Step 2: Import certificate (only if file exists)
        if Path(cert_path).exists():
            import_pfx_certificate(cert_path, cert_password, cert_nickname)
        else:
            print(f"\n[2] ⚠️  Certificate file not found at {cert_path}")
            print("     In production, the .pfx file would be:")
            print("       - Received via API")
            print("       - Written to temporary file")
            print("       - Imported into NSS database")
            print("       - Temporary file immediately deleted")
        
        # Step 3: List certificates
        personal_certs = list_certificates()
        
        if personal_certs:
            # Step 4: Write Chrome policy for auto-selection
            # Using wildcard pattern - in production, you might filter by URL
            write_chrome_policy(pattern="*")
            
            print("\n[SUCCESS] Certificate is ready for use with Chrome!")
            print("\nNext steps:")
            print("  1. Start Chrome via Selenium with these options:")
            print("     chrome_options.add_argument('--headless=new')  # or visible mode")
            print("     chrome_options.add_argument('--no-sandbox')")
            print("     chrome_options.add_argument('--disable-dev-shm-usage')")
            print("  2. Chrome will automatically use the certificate for client auth")
            print("  3. After task completion, call remove_certificate() to clean up")
            
            # Step 5: Cleanup (in production, this happens after automation completes)
            print("\n[CLEANUP] Demonstration of certificate removal...")
            if Path(cert_path).exists():
                remove_certificate(cert_nickname)
            
            # Step 6: Remove Chrome policy
            cleanup_chrome_policy()
            
            print("\n✅ Certificate management flow completed successfully!")
        else:
            print("\n⚠️  No personal certificates found in NSS database")
            print("    This is expected if the certificate file was not provided")
    
    except Exception as e:
        print(f"\n❌ Error during certificate management: {e}")
        
        # Check if this is a container environment issue
        if isinstance(e, RuntimeError) and "container environment" in str(e):
            print("\n" + "=" * 70)
            print("ℹ️  This script demonstrates the certificate management flow.")
            print("   To run it successfully, execute inside the Docker container:")
            print("\n   docker run --rm rpa-worker-selenium \\")
            print("     python example_cert_management.py")
            print("\n   Or with an actual certificate:")
            print("\n   docker run --rm -v /path/to/cert.pfx:/tmp/cert.pfx:ro \\")
            print("     rpa-worker-selenium python example_cert_management.py")
            print("=" * 70)
            return 0  # Not a real error, just not in container
        
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n" + "=" * 70)
    print("For production use:")
    print("  1. Never commit .pfx files or passwords to the image")
    print("  2. Receive certificates via API at runtime")
    print("  3. Store passwords in secure vaults (HashiCorp Vault, AWS Secrets, etc.)")
    print("  4. Always remove certificates after task completion")
    print("  5. Ensure only ONE personal certificate exists at any time")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    exit(main())
