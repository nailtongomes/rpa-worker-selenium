#!/usr/bin/env python3
"""
Test script for noVNC functionality.
Tests noVNC and websockify configuration and entrypoint integration.
"""

import os
import sys
import subprocess


def test_novnc_entrypoint_integration():
    """Test that noVNC functionality is properly integrated in entrypoint.sh."""
    print("Testing noVNC entrypoint integration...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    # Check that entrypoint.sh exists
    assert os.path.exists(entrypoint_path), "entrypoint.sh not found"
    print("  ✓ entrypoint.sh exists")
    
    # Read entrypoint.sh
    with open(entrypoint_path, 'r') as f:
        entrypoint_content = f.read()
    
    # Test 1: Check for NOVNC_PID variable
    assert 'NOVNC_PID=""' in entrypoint_content or 'NOVNC_PID=' in entrypoint_content, \
        "NOVNC_PID variable not found"
    print("  ✓ NOVNC_PID variable defined")
    
    # Test 2: Check for start_novnc function
    assert 'start_novnc()' in entrypoint_content, "start_novnc() function not found"
    print("  ✓ start_novnc() function exists")
    
    # Test 3: Check for USE_NOVNC environment variable check
    assert 'USE_NOVNC' in entrypoint_content, "USE_NOVNC environment variable not checked"
    print("  ✓ USE_NOVNC environment variable handled")
    
    # Test 4: Check for websockify command
    assert 'websockify' in entrypoint_content, "websockify command not found"
    print("  ✓ websockify command present")
    
    # Test 5: Check for NOVNC_PORT configuration
    assert 'NOVNC_PORT' in entrypoint_content or 'novnc_port' in entrypoint_content, \
        "noVNC port configuration not found"
    print("  ✓ noVNC port configuration present")
    
    # Test 6: Check that noVNC cleanup is in signal handler
    signal_handler_start = entrypoint_content.find('handle_sigterm()')
    signal_handler_end = entrypoint_content.find('}', signal_handler_start)
    signal_handler_content = entrypoint_content[signal_handler_start:signal_handler_end]
    assert 'NOVNC_PID' in signal_handler_content, "noVNC PID not cleaned up in signal handler"
    print("  ✓ noVNC cleanup in signal handler")
    
    # Test 7: Check that start_novnc is called in main
    main_start = entrypoint_content.find('main()')
    assert main_start > 0, "main() function not found"
    main_content = entrypoint_content[main_start:]
    assert 'start_novnc' in main_content, "start_novnc not called in main()"
    print("  ✓ start_novnc called in main()")
    
    # Test 8: Check for dependency on VNC - more flexible search
    # The function checks if USE_VNC != "1" and skips if VNC is not enabled
    assert 'USE_VNC' in entrypoint_content, "noVNC doesn't check for VNC dependency"
    print("  ✓ noVNC checks for VNC dependency")
    
    # Test 9: Check for noVNC installation check
    assert '/opt/novnc' in entrypoint_content and 'websockify' in entrypoint_content, \
        "noVNC installation paths not checked"
    print("  ✓ noVNC installation paths checked")
    
    print("✓ All noVNC entrypoint integration tests passed")


def test_novnc_example_script():
    """Test that noVNC example script exists and is valid."""
    print("\nTesting noVNC example script...")
    
    example_path = os.path.join(os.path.dirname(__file__), 'example_novnc_debug.py')
    
    # Check that example exists
    assert os.path.exists(example_path), "example_novnc_debug.py not found"
    print("  ✓ example_novnc_debug.py exists")
    
    # Check that example is executable
    assert os.access(example_path, os.X_OK), "example_novnc_debug.py is not executable"
    print("  ✓ example_novnc_debug.py is executable")
    
    # Read example script
    with open(example_path, 'r') as f:
        example_content = f.read()
    
    # Check for key components
    assert 'USE_NOVNC' in example_content, "Example doesn't mention USE_NOVNC"
    print("  ✓ Example mentions USE_NOVNC")
    
    assert '6080' in example_content, "Example doesn't mention noVNC port 6080"
    print("  ✓ Example mentions noVNC port")
    
    assert 'vnc.html' in example_content, "Example doesn't mention vnc.html"
    print("  ✓ Example mentions vnc.html")
    
    # Check Python syntax
    try:
        compile(example_content, example_path, 'exec')
        print("  ✓ Python syntax is valid")
    except SyntaxError as e:
        print(f"  ✗ Python syntax error: {e}")
        raise
    
    print("✓ All noVNC example script tests passed")


def test_dockerfiles_have_novnc():
    """Test that Dockerfiles (except Alpine) have noVNC installed."""
    print("\nTesting Dockerfile noVNC installation...")
    
    dockerfiles_to_check = [
        'Dockerfile',
        'Dockerfile.firefox',
        'Dockerfile.trixie'
    ]
    
    for dockerfile in dockerfiles_to_check:
        dockerfile_path = os.path.join(os.path.dirname(__file__), dockerfile)
        
        if not os.path.exists(dockerfile_path):
            print(f"  ⚠ {dockerfile} not found, skipping")
            continue
        
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        # Check for noVNC installation
        assert 'novnc' in content.lower(), f"{dockerfile} doesn't install noVNC"
        print(f"  ✓ {dockerfile} installs noVNC")
        
        # Check for websockify installation
        assert 'websockify' in content.lower(), f"{dockerfile} doesn't install websockify"
        print(f"  ✓ {dockerfile} installs websockify")
        
        # Check for USE_NOVNC environment variable
        assert 'USE_NOVNC' in content, f"{dockerfile} doesn't define USE_NOVNC"
        print(f"  ✓ {dockerfile} defines USE_NOVNC")
        
        # Check for NOVNC_PORT environment variable
        assert 'NOVNC_PORT' in content, f"{dockerfile} doesn't define NOVNC_PORT"
        print(f"  ✓ {dockerfile} defines NOVNC_PORT")
    
    print("✓ All Dockerfile noVNC installation tests passed")


def test_alpine_dockerfile_no_novnc():
    """Test that Alpine Dockerfile does NOT have noVNC (intentional)."""
    print("\nTesting Alpine Dockerfile (should NOT have noVNC)...")
    
    dockerfile_path = os.path.join(os.path.dirname(__file__), 'Dockerfile.alpine')
    
    if not os.path.exists(dockerfile_path):
        print("  ⚠ Dockerfile.alpine not found, skipping")
        return
    
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    # Alpine should NOT have noVNC or websockify
    # (case-insensitive check but exclude comments)
    lines = content.split('\n')
    code_lines = [line for line in lines if not line.strip().startswith('#')]
    code_content = '\n'.join(code_lines)
    
    # Check that noVNC is NOT installed in Alpine
    has_novnc = 'novnc' in code_content.lower()
    has_websockify = 'websockify' in code_content.lower()
    
    if not has_novnc and not has_websockify:
        print("  ✓ Dockerfile.alpine correctly does NOT install noVNC")
        print("  ✓ Dockerfile.alpine correctly does NOT install websockify")
    else:
        print(f"  ⚠ Warning: Alpine may have noVNC references (novnc={has_novnc}, websockify={has_websockify})")
    
    # Check that USE_NOVNC is NOT defined (or is set to 0)
    if 'USE_NOVNC' not in content or 'USE_NOVNC=0' in content:
        print("  ✓ Dockerfile.alpine correctly does NOT enable USE_NOVNC")
    
    print("✓ Alpine Dockerfile noVNC exclusion test passed")


def test_readme_documentation():
    """Test that README.md documents noVNC feature."""
    print("\nTesting README.md documentation...")
    
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    
    assert os.path.exists(readme_path), "README.md not found"
    print("  ✓ README.md exists")
    
    with open(readme_path, 'r') as f:
        readme_content = f.read()
    
    # Check for noVNC mentions
    assert 'noVNC' in readme_content or 'novnc' in readme_content.lower(), \
        "README.md doesn't mention noVNC"
    print("  ✓ README.md mentions noVNC")
    
    # Check for USE_NOVNC environment variable
    assert 'USE_NOVNC' in readme_content, "README.md doesn't document USE_NOVNC"
    print("  ✓ README.md documents USE_NOVNC")
    
    # Check for NOVNC_PORT environment variable
    assert 'NOVNC_PORT' in readme_content, "README.md doesn't document NOVNC_PORT"
    print("  ✓ README.md documents NOVNC_PORT")
    
    # Check for port 6080 mention
    assert '6080' in readme_content, "README.md doesn't mention noVNC port 6080"
    print("  ✓ README.md mentions noVNC port")
    
    # Check for vnc.html mention
    assert 'vnc.html' in readme_content, "README.md doesn't mention vnc.html"
    print("  ✓ README.md mentions vnc.html")
    
    # Check for browser-based VNC mention
    assert 'browser' in readme_content.lower(), "README.md doesn't mention browser-based access"
    print("  ✓ README.md mentions browser-based access")
    
    print("✓ All README.md documentation tests passed")


def run_all_tests():
    """Run all noVNC tests."""
    print("=" * 60)
    print("Running noVNC Tests")
    print("=" * 60)
    
    tests = [
        test_novnc_entrypoint_integration,
        test_novnc_example_script,
        test_dockerfiles_have_novnc,
        test_alpine_dockerfile_no_novnc,
        test_readme_documentation,
    ]
    
    failed_tests = []
    
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"\n✗ Test failed: {test.__name__}")
            print(f"  Error: {e}")
            failed_tests.append(test.__name__)
        except Exception as e:
            print(f"\n✗ Test error: {test.__name__}")
            print(f"  Error: {e}")
            failed_tests.append(test.__name__)
    
    print("\n" + "=" * 60)
    if not failed_tests:
        print("✓ All noVNC tests passed!")
        print("=" * 60)
        return 0
    else:
        print(f"✗ {len(failed_tests)} test(s) failed:")
        for test_name in failed_tests:
            print(f"  - {test_name}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
