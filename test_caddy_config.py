#!/usr/bin/env python3
"""
Test script for Caddy reverse proxy configuration.
Validates the Caddy setup files and configurations.
"""

import os
import sys
import yaml


def test_docker_compose_caddy():
    """Test docker-compose.caddy.yml structure."""
    print("Testing docker-compose.caddy.yml...")
    
    compose_path = os.path.join(os.path.dirname(__file__), 'docker-compose.caddy.yml')
    
    assert os.path.exists(compose_path), "docker-compose.caddy.yml not found"
    print("  ✓ docker-compose.caddy.yml exists")
    
    # Load and validate YAML
    with open(compose_path, 'r') as f:
        compose = yaml.safe_load(f)
    
    assert 'services' in compose, "services section not found"
    print("  ✓ Valid YAML structure")
    
    # Check required services
    required_services = ['rpa-worker-vnc', 'caddy', 'novnc']
    for service in required_services:
        assert service in compose['services'], f"{service} service not found"
        print(f"  ✓ {service} service defined")
    
    # Check rpa-worker-vnc configuration
    rpa_worker = compose['services']['rpa-worker-vnc']
    assert 'environment' in rpa_worker, "rpa-worker-vnc missing environment"
    env = rpa_worker['environment']
    env_dict = {e.split('=')[0]: e.split('=')[1] for e in env}
    
    assert env_dict.get('USE_XVFB') == '1', "USE_XVFB not enabled"
    assert env_dict.get('USE_VNC') == '1', "USE_VNC not enabled"
    print("  ✓ rpa-worker-vnc properly configured for VNC")
    
    # Check caddy configuration
    caddy = compose['services']['caddy']
    assert 'ports' in caddy, "caddy missing ports"
    assert 'volumes' in caddy, "caddy missing volumes"
    
    # Check Caddyfile is mounted
    caddyfile_mounted = any('./Caddyfile' in str(v) for v in caddy['volumes'])
    assert caddyfile_mounted, "Caddyfile not mounted in caddy service"
    print("  ✓ Caddy properly configured")
    
    # Check noVNC configuration
    novnc = compose['services']['novnc']
    assert 'command' in novnc, "novnc missing command"
    assert 'rpa-worker-vnc:5900' in str(novnc['command']), "novnc not pointing to correct VNC server"
    print("  ✓ noVNC properly configured")
    
    # Check network
    assert 'networks' in compose, "networks section not found"
    print("  ✓ Network configuration present")
    
    print("✓ All docker-compose.caddy.yml tests passed!\n")


def test_caddyfile_exists():
    """Test Caddyfile exists and has basic structure."""
    print("Testing Caddyfile...")
    
    caddyfile_path = os.path.join(os.path.dirname(__file__), 'Caddyfile')
    
    assert os.path.exists(caddyfile_path), "Caddyfile not found"
    print("  ✓ Caddyfile exists")
    
    with open(caddyfile_path, 'r') as f:
        content = f.read()
    
    # Check for key configurations
    checks = [
        (':5901', 'Port configuration'),
        ('reverse_proxy', 'Reverse proxy directive'),
        ('rpa-worker-vnc:5900', 'VNC backend reference'),
        ('header_up Upgrade', 'WebSocket support (Upgrade header)'),
        ('header_up Connection', 'WebSocket support (Connection header)'),
    ]
    
    for check_str, description in checks:
        assert check_str in content, f"{description} not found in Caddyfile"
        print(f"  ✓ {description} present")
    
    print("✓ All Caddyfile tests passed!\n")


def test_caddy_documentation():
    """Test VNC_CADDY_PROXY.md documentation."""
    print("Testing VNC_CADDY_PROXY.md...")
    
    doc_path = os.path.join(os.path.dirname(__file__), 'VNC_CADDY_PROXY.md')
    
    assert os.path.exists(doc_path), "VNC_CADDY_PROXY.md not found"
    print("  ✓ VNC_CADDY_PROXY.md exists")
    
    with open(doc_path, 'r') as f:
        content = f.read()
    
    # Check for essential sections
    sections = [
        'Caddy Reverse Proxy',
        'Why Use a Reverse Proxy',
        'Prerequisites',
        'Setup with Caddy',
        'docker-compose.caddy.yml',
        'Caddyfile',
        'Usage Instructions',
        'Security Best Practices',
        'HTTPS',
        'Authentication',
        'Troubleshooting',
        'noVNC',
    ]
    
    for section in sections:
        assert section in content, f"Section '{section}' not found in documentation"
        print(f"  ✓ {section} section present")
    
    # Check for code examples
    assert '```yaml' in content, "YAML code examples not found"
    assert '```bash' in content, "Bash code examples not found"
    assert '```caddyfile' in content, "Caddyfile examples not found"
    print("  ✓ Code examples present")
    
    # Check for security warnings
    assert 'password' in content.lower() or 'authentication' in content.lower(), \
        "Security/authentication information not found"
    print("  ✓ Security information present")
    
    print("✓ All VNC_CADDY_PROXY.md tests passed!\n")


def test_readme_caddy_reference():
    """Test that README.md references Caddy documentation."""
    print("Testing README.md Caddy references...")
    
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    
    with open(readme_path, 'r') as f:
        content = f.read()
    
    # Check for Caddy references
    assert 'VNC_CADDY_PROXY.md' in content, "VNC_CADDY_PROXY.md not referenced in README"
    print("  ✓ VNC_CADDY_PROXY.md referenced in README")
    
    assert 'docker-compose.caddy.yml' in content or 'Caddy' in content, \
        "Caddy not mentioned in README"
    print("  ✓ Caddy mentioned in README")
    
    print("✓ All README Caddy reference tests passed!\n")


def test_dockerfile_trixie_tkinter():
    """Test that Dockerfile.trixie includes python3-tk."""
    print("Testing Dockerfile.trixie tkinter fix...")

    dockerfile_path = os.path.join(os.path.dirname(__file__), 'Dockerfile.trixie')

    assert os.path.exists(dockerfile_path), "Dockerfile.trixie not found"

    with open(dockerfile_path, 'r') as f:
        content = f.read()

    # Check for python3-tk
    assert 'python3-tk' in content, "python3-tk not found in Dockerfile.trixie"
    print("  ✓ python3-tk package included")

    # Check it's in the Python section
    lines = content.split('\n')
    found_python_section = False
    found_tk = False

    for i, line in enumerate(lines):
        if 'Python and build tools' in line or 'python3-dev' in line:
            found_python_section = True
        if found_python_section and 'python3-tk' in line:
            found_tk = True
            break
        if found_python_section and line.strip() and line.strip().startswith('#') and 'Python' not in line:
            break  # Moved to next section

    assert found_tk, "python3-tk not in Python tools section"
    print("  ✓ python3-tk in correct section (Python build tools)")

    # Verify python3-dev is still there
    assert 'python3-dev' in content, "python3-dev missing (should still be present)"
    print("  ✓ python3-dev still present")

    print("✓ All Dockerfile.trixie tkinter tests passed!\n")


def main():
    """Run all tests."""
    print("=" * 70)
    print("Caddy Reverse Proxy Configuration Test Suite")
    print("=" * 70)
    print()
    
    try:
        test_docker_compose_caddy()
        test_caddyfile_exists()
        test_caddy_documentation()
        test_readme_caddy_reference()
        test_dockerfile_trixie_tkinter()
        
        print("=" * 70)
        print("✓ All Caddy configuration tests passed successfully!")
        print("=" * 70)
        print()
        print("To use Caddy reverse proxy:")
        print("  docker-compose -f docker-compose.caddy.yml up -d")
        print("  open http://localhost:8080")
        print()
        print("See VNC_CADDY_PROXY.md for complete documentation.")
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
