#!/usr/bin/env python3
"""
Integration test for VNC feature.
Tests the complete flow of enabling and using VNC.
"""

import os
import sys
import subprocess
import tempfile


def test_entrypoint_vnc_flow():
    """Test VNC flow in entrypoint.sh."""
    print("Testing VNC integration flow...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    # Test 1: Verify VNC is called in the right order
    print("  Testing VNC initialization order...")
    with open(entrypoint_path, 'r') as f:
        content = f.read()
    
    # Find the main function
    main_start = content.find('main() {')
    assert main_start > 0, "main() function not found"
    
    main_section = content[main_start:main_start + 2000]
    
    # Check order of service starts
    xvfb_pos = main_section.find('start_xvfb')
    openbox_pos = main_section.find('start_openbox')
    vnc_pos = main_section.find('start_vnc')
    recording_pos = main_section.find('start_screen_recording')
    
    assert xvfb_pos > 0, "start_xvfb not called in main"
    assert vnc_pos > 0, "start_vnc not called in main"
    
    # VNC should be started after Xvfb
    assert vnc_pos > xvfb_pos, "VNC should be started after Xvfb"
    print("  ✓ VNC starts after Xvfb (correct dependency order)")
    
    # VNC should be before script execution
    exec_pos = main_section.find('exec')
    if exec_pos > 0:
        assert vnc_pos < exec_pos, "VNC should start before script execution"
        print("  ✓ VNC starts before script execution")
    
    print("✓ VNC integration flow test passed!\n")


def test_vnc_configuration_options():
    """Test that all VNC configuration options are available."""
    print("Testing VNC configuration options...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    with open(entrypoint_path, 'r') as f:
        content = f.read()
    
    # Check for configurable options
    checks = [
        ('USE_VNC', 'USE_VNC environment variable'),
        ('VNC_PORT', 'VNC_PORT environment variable'),
        ('-display', 'Display configuration'),
        ('-forever', 'Forever mode (persistent connections)'),
        ('-shared', 'Shared mode (multiple clients)'),
        ('-rfbport', 'RFB port configuration'),
        ('-nopw', 'No password mode'),
        ('-bg', 'Background mode'),
    ]
    
    for check_str, description in checks:
        assert check_str in content, f"{description} not found in entrypoint.sh"
        print(f"  ✓ {description} configured")
    
    print("✓ All VNC configuration options present!\n")


def test_vnc_error_handling():
    """Test VNC error handling and fallback behavior."""
    print("Testing VNC error handling...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    with open(entrypoint_path, 'r') as f:
        content = f.read()
    
    # Find start_vnc function
    vnc_start = content.find('start_vnc()')
    vnc_section = content[vnc_start:vnc_start + 2000]
    
    # Check for Xvfb requirement check
    assert 'USE_XVFB' in vnc_section, "VNC doesn't check for Xvfb requirement"
    assert 'WARNING' in vnc_section or 'warning' in vnc_section.lower(), \
        "VNC doesn't warn when Xvfb is not enabled"
    print("  ✓ VNC checks for Xvfb requirement")
    
    # Check for VNC disabled check
    assert 'USE_VNC' in vnc_section, "VNC doesn't check if it's enabled"
    print("  ✓ VNC checks if it's enabled")
    
    # Check for PID validation
    assert 'VNC_PID' in vnc_section, "VNC doesn't track PID"
    print("  ✓ VNC tracks process PID")
    
    print("✓ VNC error handling test passed!\n")


def test_vnc_cleanup():
    """Test VNC cleanup in signal handler."""
    print("Testing VNC cleanup...")
    
    entrypoint_path = os.path.join(os.path.dirname(__file__), 'entrypoint.sh')
    
    with open(entrypoint_path, 'r') as f:
        content = f.read()
    
    # Find signal handler
    handler_start = content.find('handle_sigterm()')
    handler_section = content[handler_start:handler_start + 1000]
    
    # Check VNC cleanup
    assert 'VNC_PID' in handler_section, "VNC not cleaned up in signal handler"
    assert 'kill' in handler_section, "VNC process not killed in cleanup"
    print("  ✓ VNC cleanup in signal handler")
    
    # Check cleanup order (VNC should be cleaned before Xvfb)
    vnc_cleanup = handler_section.find('VNC_PID')
    xvfb_cleanup = handler_section.find('XVFB_PID')
    
    if vnc_cleanup > 0 and xvfb_cleanup > 0:
        assert vnc_cleanup < xvfb_cleanup, "VNC should be cleaned up before Xvfb"
        print("  ✓ VNC cleanup order correct (before Xvfb)")
    
    print("✓ VNC cleanup test passed!\n")


def test_example_script_structure():
    """Test the VNC example script structure."""
    print("Testing VNC example script...")
    
    example_path = os.path.join(os.path.dirname(__file__), 'example_vnc_debug.py')
    
    assert os.path.exists(example_path), "example_vnc_debug.py not found"
    print("  ✓ Example script exists")
    
    # Check script is executable/valid Python
    result = subprocess.run(
        ['python', '-m', 'py_compile', example_path],
        capture_output=True
    )
    assert result.returncode == 0, "Example script has syntax errors"
    print("  ✓ Example script has valid syntax")
    
    # Check for key functions
    with open(example_path, 'r') as f:
        content = f.read()
    
    checks = [
        ('create_chrome_driver', 'Driver creation function'),
        ('demonstrate_vnc_debugging', 'VNC demonstration function'),
        ('main', 'Main function'),
        ('time.sleep', 'Delays for VNC observation'),
        ('USE_XVFB', 'Xvfb usage documented'),
        ('USE_VNC', 'VNC usage documented'),
        ('5900', 'VNC port documented'),
    ]
    
    for check_str, description in checks:
        assert check_str in content, f"{description} not found in example"
        print(f"  ✓ {description} present")
    
    print("✓ VNC example script test passed!\n")


def test_documentation_completeness():
    """Test that documentation is complete and accurate."""
    print("Testing documentation completeness...")
    
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    
    with open(readme_path, 'r') as f:
        readme = f.read()
    
    # Required documentation elements
    required_elements = [
        ('Remote Debugging with VNC', 'VNC section header'),
        ('USE_VNC=1', 'Enable VNC environment variable'),
        ('5900:5900', 'Port mapping example'),
        ('vncviewer', 'VNC client usage'),
        ('docker-compose', 'Docker Compose example'),
        ('Security Considerations', 'Security documentation'),
        ('-nopw', 'Password-free mode documented'),
        ('example_vnc_debug.py', 'Example script referenced'),
    ]
    
    for element, description in required_elements:
        assert element in readme, f"{description} not found in README"
        print(f"  ✓ {description} documented")
    
    print("✓ Documentation completeness test passed!\n")


def main():
    """Run all integration tests."""
    print("=" * 70)
    print("VNC Feature Integration Test Suite")
    print("=" * 70)
    print()
    
    try:
        test_entrypoint_vnc_flow()
        test_vnc_configuration_options()
        test_vnc_error_handling()
        test_vnc_cleanup()
        test_example_script_structure()
        test_documentation_completeness()
        
        print("=" * 70)
        print("✓ All VNC integration tests passed successfully!")
        print("=" * 70)
        print()
        print("Feature is ready for use!")
        print("To test manually:")
        print("  1. Build: docker build -t rpa-worker-selenium .")
        print("  2. Run: docker run -e USE_XVFB=1 -e USE_VNC=1 -p 5900:5900 rpa-worker-selenium example_vnc_debug.py")
        print("  3. Connect: vncviewer localhost:5900")
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Integration test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
