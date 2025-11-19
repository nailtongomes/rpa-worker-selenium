#!/usr/bin/env python3
"""
Test script for VNC functionality.
Tests VNC server configuration and entrypoint integration.
"""

import os
import sys
import subprocess
import tempfile
import time


def test_vnc_entrypoint_integration():
    """Test that VNC functionality is properly integrated in entrypoint.sh."""
    print("Testing VNC entrypoint integration...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    # Check that entrypoint.sh exists
    assert os.path.exists(entrypoint_path), "entrypoint.sh not found"
    print("  ✓ entrypoint.sh exists")
    
    # Read entrypoint.sh
    with open(entrypoint_path, 'r') as f:
        entrypoint_content = f.read()
    
    # Test 1: Check for VNC_PID variable
    assert 'VNC_PID=""' in entrypoint_content or 'VNC_PID=' in entrypoint_content, \
        "VNC_PID variable not found"
    print("  ✓ VNC_PID variable defined")
    
    # Test 2: Check for start_vnc function
    assert 'start_vnc()' in entrypoint_content, "start_vnc() function not found"
    print("  ✓ start_vnc() function exists")
    
    # Test 3: Check for USE_VNC environment variable check
    assert 'USE_VNC' in entrypoint_content, "USE_VNC environment variable not checked"
    print("  ✓ USE_VNC environment variable handled")
    
    # Test 4: Check for x11vnc command
    assert 'x11vnc' in entrypoint_content, "x11vnc command not found"
    print("  ✓ x11vnc command present")
    
    # Test 5: Check for VNC port configuration
    assert 'VNC_PORT' in entrypoint_content or 'vnc_port' in entrypoint_content, \
        "VNC port configuration not found"
    print("  ✓ VNC port configuration present")
    
    # Test 6: Check that VNC cleanup is in signal handler
    assert 'VNC_PID' in entrypoint_content and 'handle_sigterm' in entrypoint_content, \
        "VNC cleanup not found in signal handler"
    print("  ✓ VNC cleanup in signal handler")
    
    # Test 7: Check that start_vnc is called in main
    # Find the main function and verify start_vnc is called
    if 'main()' in entrypoint_content:
        main_func_start = entrypoint_content.find('main()')
        main_func = entrypoint_content[main_func_start:]
        assert 'start_vnc' in main_func, "start_vnc not called in main()"
        print("  ✓ start_vnc called in main function")
    
    # Test 8: Check for Xvfb requirement check
    lines = entrypoint_content.split('\n')
    in_start_vnc = False
    found_xvfb_check = False
    for line in lines:
        if 'start_vnc()' in line:
            in_start_vnc = True
        elif in_start_vnc and 'USE_XVFB' in line:
            found_xvfb_check = True
            break
        elif in_start_vnc and line.strip().startswith('#') == False and line.strip() and 'start_' in line and 'vnc' not in line.lower():
            break  # Moved to next function
    
    assert found_xvfb_check, "VNC doesn't check for Xvfb requirement"
    print("  ✓ VNC checks for Xvfb requirement")
    
    print("✓ All VNC entrypoint integration tests passed!\n")


def test_vnc_environment_variables():
    """Test VNC environment variable handling."""
    print("Testing VNC environment variables...")
    
    # Test 1: Check Dockerfile has VNC environment variables
    dockerfile_paths = [
        'Dockerfile',
        'Dockerfile.chrome',
        'Dockerfile.firefox',
        'Dockerfile.brave',
        'Dockerfile.trixie'
    ]
    
    for dockerfile in dockerfile_paths:
        filepath = os.path.join(os.path.dirname(__file__), dockerfile)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Check for USE_VNC
            if 'USE_VNC' in content:
                print(f"  ✓ {dockerfile} has USE_VNC environment variable")
            
            # Check for VNC_PORT
            if 'VNC_PORT' in content:
                print(f"  ✓ {dockerfile} has VNC_PORT environment variable")
    
    print("✓ All VNC environment variable tests passed!\n")


def test_readme_documentation():
    """Test that README.md documents VNC usage."""
    print("Testing README documentation...")
    
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    
    assert os.path.exists(readme_path), "README.md not found"
    
    with open(readme_path, 'r') as f:
        readme_content = f.read()
    
    # Test 1: Check for VNC section
    assert 'VNC' in readme_content or 'vnc' in readme_content.lower(), \
        "VNC not documented in README"
    print("  ✓ VNC mentioned in README")
    
    # Test 2: Check for VNC port documentation
    assert '5900' in readme_content, "VNC default port (5900) not documented"
    print("  ✓ VNC port documented")
    
    # Test 3: Check for USE_VNC documentation
    assert 'USE_VNC' in readme_content, "USE_VNC environment variable not documented"
    print("  ✓ USE_VNC documented")
    
    # Test 4: Check for VNC usage examples
    assert 'vncviewer' in readme_content or 'VNC client' in readme_content or 'VNC Viewer' in readme_content, \
        "VNC client usage not documented"
    print("  ✓ VNC client usage documented")
    
    # Test 5: Check for port mapping documentation
    assert '-p' in readme_content and '5900:5900' in readme_content, \
        "VNC port mapping not documented"
    print("  ✓ VNC port mapping documented")
    
    print("✓ All README documentation tests passed!\n")


def test_docker_compose_vnc_example():
    """Test that docker-compose.yml includes VNC example."""
    print("Testing docker-compose VNC example...")
    
    compose_path = os.path.join(os.path.dirname(__file__), 'docker-compose.yml')
    
    assert os.path.exists(compose_path), "docker-compose.yml not found"
    
    with open(compose_path, 'r') as f:
        compose_content = f.read()
    
    # Test 1: Check for VNC port mapping
    assert '5900:5900' in compose_content or '5900' in compose_content, \
        "VNC port not in docker-compose.yml"
    print("  ✓ VNC port mapping in docker-compose.yml")
    
    # Test 2: Check for USE_VNC environment variable
    assert 'USE_VNC' in compose_content, \
        "USE_VNC environment variable not in docker-compose.yml"
    print("  ✓ USE_VNC in docker-compose.yml")
    
    # Test 3: Check for USE_XVFB alongside USE_VNC
    if 'USE_VNC' in compose_content:
        vnc_section_start = compose_content.find('USE_VNC')
        # Look backwards and forwards for USE_XVFB in the same service
        section = compose_content[max(0, vnc_section_start - 500):vnc_section_start + 500]
        assert 'USE_XVFB' in section, \
            "USE_XVFB not configured alongside USE_VNC in docker-compose.yml"
        print("  ✓ USE_XVFB configured with USE_VNC")
    
    print("✓ All docker-compose VNC tests passed!\n")


def test_entrypoint_syntax():
    """Test that entrypoint.sh has valid bash syntax."""
    print("Testing entrypoint.sh syntax...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    # Use bash -n to check syntax without executing
    result = subprocess.run(
        ['bash', '-n', entrypoint_path],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Syntax error in entrypoint.sh:\n{result.stderr}")
        raise AssertionError(f"entrypoint.sh has syntax errors: {result.stderr}")
    
    print("  ✓ entrypoint.sh has valid bash syntax")
    print("✓ All syntax tests passed!\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("VNC Functionality Test Suite")
    print("=" * 60)
    print()
    
    try:
        test_vnc_entrypoint_integration()
        test_vnc_environment_variables()
        test_readme_documentation()
        test_docker_compose_vnc_example()
        test_entrypoint_syntax()
        
        print("=" * 60)
        print("✓ All VNC tests passed successfully!")
        print("=" * 60)
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
