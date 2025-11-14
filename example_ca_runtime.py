#!/usr/bin/env python3
"""
Example: Runtime CA Certificate Management

This example demonstrates how to install, list, and remove CA certificates
at runtime in rpa-worker-selenium Docker containers. This is useful for:
  - Corporate environments with custom CAs
  - Systems requiring authentication with specific Certificate Authorities
  - Testing with self-signed certificates

Requirements:
  - Container built from any rpa-worker-selenium Dockerfile
  - ca-certificates package (pre-installed)
  - Root access (default in containers)

Usage:
  # Install a CA certificate
  docker run --rm -v /path/to/ca.crt:/tmp/ca.crt:ro \\
    rpa-worker-selenium python example_ca_runtime.py --install /tmp/ca.crt

  # List installed CA certificates
  docker run --rm rpa-worker-selenium python example_ca_runtime.py --list

  # Remove a CA certificate
  docker run --rm rpa-worker-selenium python example_ca_runtime.py --remove my-ca

Author: RPA Worker Selenium Team
"""

import argparse
import os
import subprocess
import shutil
import sys
from pathlib import Path


class CACertificateManager:
    """Manage system CA certificates at runtime."""
    
    def __init__(self):
        self.ca_dir = Path("/usr/local/share/ca-certificates")
        self.ca_dir.mkdir(parents=True, exist_ok=True)
        self.system_ca_dir = Path("/etc/ssl/certs")
    
    def install(self, cert_path: str, cert_name: str = None):
        """
        Install a CA certificate at runtime.
        
        Args:
            cert_path: Path to the .crt or .pem certificate file
            cert_name: Optional name for the certificate (without extension)
        """
        cert_path = Path(cert_path)
        
        if not cert_path.exists():
            raise FileNotFoundError(f"Certificate not found: {cert_path}")
        
        # Verify certificate format
        if not self.verify_certificate(cert_path):
            raise ValueError(f"Invalid certificate format: {cert_path}")
        
        if cert_name is None:
            cert_name = cert_path.stem
        
        # Ensure .crt extension
        if not cert_name.endswith('.crt'):
            cert_name += '.crt'
        
        dest_path = self.ca_dir / cert_name
        
        print(f"📋 Installing CA certificate...")
        print(f"   Source: {cert_path}")
        print(f"   Destination: {dest_path}")
        
        # Copy certificate to system CA directory
        shutil.copy(cert_path, dest_path)
        os.chmod(dest_path, 0o644)
        
        # Update system CA trust store
        print(f"🔄 Updating system CA trust store...")
        result = subprocess.run(
            ["update-ca-certificates"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ CA certificate '{cert_name}' installed successfully")
            print(f"   {result.stdout.strip()}")
            return True
        else:
            print(f"❌ Failed to install CA certificate")
            print(f"   {result.stderr}")
            raise RuntimeError("Certificate installation failed")
    
    def list(self, verbose=False):
        """
        List installed custom CA certificates.
        
        Args:
            verbose: Show detailed information about each certificate
        """
        # List custom certificates
        custom_certs = list(self.ca_dir.glob("*.crt"))
        
        print(f"\n📁 Custom CA Certificates ({len(custom_certs)}):")
        print(f"   Location: {self.ca_dir}")
        
        if not custom_certs:
            print("   (none installed)")
        else:
            for cert in sorted(custom_certs):
                if verbose:
                    print(f"\n   📜 {cert.name}")
                    self._print_cert_info(cert)
                else:
                    print(f"   - {cert.name}")
        
        # Show system CA stats
        system_certs = list(self.system_ca_dir.glob("*.pem"))
        print(f"\n📦 System CA Certificates: {len(system_certs)}")
        print(f"   Location: {self.system_ca_dir}")
        
        return [cert.name for cert in custom_certs]
    
    def remove(self, cert_name: str):
        """
        Remove a CA certificate at runtime.
        
        Args:
            cert_name: Name of the certificate (without extension)
        """
        if not cert_name.endswith('.crt'):
            cert_name += '.crt'
        
        cert_path = self.ca_dir / cert_name
        
        if not cert_path.exists():
            print(f"⚠️  Certificate '{cert_name}' not found in {self.ca_dir}")
            print(f"   Available certificates:")
            self.list()
            return False
        
        print(f"🗑️  Removing CA certificate: {cert_name}")
        
        # Remove the certificate file
        cert_path.unlink()
        
        # Rebuild CA trust store
        print(f"🔄 Rebuilding system CA trust store...")
        result = subprocess.run(
            ["update-ca-certificates", "--fresh"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ CA certificate '{cert_name}' removed successfully")
            print(f"   {result.stdout.strip()}")
            return True
        else:
            print(f"❌ Failed to remove CA certificate")
            print(f"   {result.stderr}")
            return False
    
    def verify_certificate(self, cert_path: Path):
        """
        Verify a certificate file is valid.
        
        Args:
            cert_path: Path to certificate file
        
        Returns:
            bool: True if certificate is valid
        """
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-noout"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"⚠️  Certificate verification failed:")
            print(f"   {result.stderr}")
            return False
    
    def _print_cert_info(self, cert_path: Path):
        """Print detailed certificate information."""
        result = subprocess.run(
            [
                "openssl", "x509", 
                "-in", str(cert_path),
                "-noout",
                "-subject",
                "-issuer",
                "-dates"
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                print(f"       {line}")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description='Manage CA certificates at runtime',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Install a CA certificate
  python example_ca_runtime.py --install /path/to/ca.crt
  
  # Install with custom name
  python example_ca_runtime.py --install /path/to/ca.crt --name my-custom-ca
  
  # List all CA certificates
  python example_ca_runtime.py --list
  
  # List with details
  python example_ca_runtime.py --list --verbose
  
  # Remove a CA certificate
  python example_ca_runtime.py --remove my-custom-ca
        """
    )
    
    parser.add_argument(
        '--install', 
        metavar='PATH',
        help='Install a CA certificate from file'
    )
    parser.add_argument(
        '--name',
        metavar='NAME',
        help='Custom name for the certificate (used with --install)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List installed CA certificates'
    )
    parser.add_argument(
        '--remove',
        metavar='NAME',
        help='Remove a CA certificate by name'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )
    
    args = parser.parse_args()
    
    # Check if running as root
    if os.geteuid() != 0:
        print("⚠️  Warning: This script requires root privileges")
        print("   Running as non-root may fail to update system certificates")
    
    manager = CACertificateManager()
    
    try:
        if args.install:
            print("=" * 70)
            print("CA Certificate Installation")
            print("=" * 70)
            manager.install(args.install, args.name)
            
        elif args.list:
            print("=" * 70)
            print("CA Certificate Listing")
            print("=" * 70)
            manager.list(verbose=args.verbose)
            
        elif args.remove:
            print("=" * 70)
            print("CA Certificate Removal")
            print("=" * 70)
            manager.remove(args.remove)
            
        else:
            parser.print_help()
            print("\n" + "=" * 70)
            print("ℹ️  Quick Start:")
            print("   1. Install: python example_ca_runtime.py --install /path/to/ca.crt")
            print("   2. List:    python example_ca_runtime.py --list")
            print("   3. Remove:  python example_ca_runtime.py --remove ca-name")
            print("=" * 70)
            return 0
        
        print("=" * 70)
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        if args.verbose:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
