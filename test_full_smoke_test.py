#!/usr/bin/env python3
"""
Unit tests for full_smoke_test.py
Tests the comprehensive smoke test functionality.
"""

import os
import sys
import tempfile
import json
import pathlib
from unittest.mock import patch, MagicMock


def test_imports():
    """Test that full_smoke_test.py can be imported without errors."""
    print("Testing full_smoke_test.py imports...")
    
    # Set required environment variables before import
    os.environ['DISPLAY'] = ':99'
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        import full_smoke_test
        print("  ✓ full_smoke_test module imported successfully")
        return True
    except Exception as e:
        print(f"  ✗ Failed to import full_smoke_test: {e}")
        return False


def test_log_function():
    """Test the log function."""
    print("Testing log function...")
    
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        from full_smoke_test import log, log_verbose
        
        # Test basic logging
        log("Test message")
        log("Test error", "ERROR")
        
        # Test verbose logging
        os.environ['VERBOSE'] = '1'
        import importlib
        import full_smoke_test as fsm
        importlib.reload(fsm)
        
        print("  ✓ Log functions work correctly")
        return True
    except Exception as e:
        print(f"  ✗ Log function test failed: {e}")
        return False


def test_record_test_function():
    """Test the record_test function."""
    print("Testing record_test function...")
    
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        from full_smoke_test import record_test, test_results
        
        # Clear existing results
        test_results.clear()
        
        # Record a passing test
        record_test("test_pass", True, "This test passed")
        assert "test_pass" in test_results
        assert test_results["test_pass"]["passed"] is True
        
        # Record a failing test
        record_test("test_fail", False, "This test failed")
        assert "test_fail" in test_results
        assert test_results["test_fail"]["passed"] is False
        
        print("  ✓ record_test function works correctly")
        return True
    except Exception as e:
        print(f"  ✗ record_test function test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_check_python_version():
    """Test Python version check."""
    print("Testing check_python_version function...")
    
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        from full_smoke_test import check_python_version, test_results
        
        test_results.clear()
        result = check_python_version()
        
        # Should pass for Python 3.8+
        assert result is True
        assert "python_version" in test_results
        assert test_results["python_version"]["passed"] is True
        
        print("  ✓ check_python_version works correctly")
        return True
    except Exception as e:
        print(f"  ✗ check_python_version test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_check_process_alive():
    """Test process alive check."""
    print("Testing check_process_alive function...")
    
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        from full_smoke_test import check_process_alive
        
        # Test with a process that should exist (bash or python)
        result = check_process_alive("bash")
        # Result can be True or False depending on system, just check it runs
        assert isinstance(result, bool)
        
        # Test with a process that shouldn't exist
        result = check_process_alive("nonexistent_process_12345")
        assert result is False
        
        print("  ✓ check_process_alive works correctly")
        return True
    except Exception as e:
        print(f"  ✗ check_process_alive test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_filesystem_operations():
    """Test filesystem operations test function."""
    print("Testing test_filesystem_operations function...")
    
    cache_dir = tempfile.mkdtemp()
    os.environ['CACHE_DIR'] = cache_dir
    
    try:
        import importlib
        import full_smoke_test as fsm
        importlib.reload(fsm)
        
        fsm.test_results.clear()
        result = fsm.test_filesystem_operations()
        
        # Should pass
        assert result is True
        assert "filesystem_operations" in fsm.test_results
        assert fsm.test_results["filesystem_operations"]["passed"] is True
        
        print("  ✓ test_filesystem_operations works correctly")
        return True
    except Exception as e:
        print(f"  ✗ test_filesystem_operations test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_script_downloader_test():
    """Test script downloader test function."""
    print("Testing test_script_downloader function...")
    
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        from full_smoke_test import test_script_downloader, test_results
        
        test_results.clear()
        result = test_script_downloader()
        
        # Should pass
        assert result is True
        assert "script_downloader" in test_results
        assert test_results["script_downloader"]["passed"] is True
        
        print("  ✓ test_script_downloader works correctly")
        return True
    except Exception as e:
        print(f"  ✗ test_script_downloader test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_environment_variables_test():
    """Test environment variables test function."""
    print("Testing test_environment_variables function...")
    
    os.environ['CACHE_DIR'] = tempfile.mkdtemp()
    
    try:
        from full_smoke_test import test_environment_variables, test_results
        
        test_results.clear()
        result = test_environment_variables()
        
        # Should pass
        assert result is True
        assert "environment_variables" in test_results
        assert test_results["environment_variables"]["passed"] is True
        
        print("  ✓ test_environment_variables works correctly")
        return True
    except Exception as e:
        print(f"  ✗ test_environment_variables test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_report_generation():
    """Test report generation."""
    print("Testing generate_report function...")
    
    cache_dir = tempfile.mkdtemp()
    os.environ['CACHE_DIR'] = cache_dir
    
    try:
        import importlib
        import full_smoke_test as fsm
        importlib.reload(fsm)
        
        # Add some test results
        fsm.test_results.clear()
        fsm.record_test("test1", True, "Test 1 passed")
        fsm.record_test("test2", False, "Test 2 failed")
        fsm.record_test("test3", True, "Test 3 passed")
        
        passed, total = fsm.generate_report()
        
        assert passed == 2
        assert total == 3
        
        # Check if report file was created
        report_files = list(pathlib.Path(cache_dir).glob("full_smoke_test_report_*.json"))
        assert len(report_files) > 0
        
        # Check report content
        with open(report_files[0]) as f:
            report = json.load(f)
            assert report["total_tests"] == 3
            assert report["passed"] == 2
            assert report["failed"] == 1
            assert "test1" in report["tests"]
            assert "test2" in report["tests"]
            assert "test3" in report["tests"]
        
        print("  ✓ generate_report works correctly")
        return True
    except Exception as e:
        print(f"  ✗ generate_report test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_configuration_from_env():
    """Test configuration from environment variables."""
    print("Testing configuration from environment variables...")
    
    cache_dir = tempfile.mkdtemp()
    
    try:
        # Set custom environment variables
        os.environ['TARGET_URL'] = 'https://test.example.com'
        os.environ['CACHE_DIR'] = cache_dir
        os.environ['TEST_ALL_BROWSERS'] = '1'
        os.environ['CHECK_PROCESSES'] = '1'
        os.environ['VERBOSE'] = '1'
        
        # Reload module to pick up new env vars
        import importlib
        import full_smoke_test as fsm
        importlib.reload(fsm)
        
        assert fsm.TARGET_URL == 'https://test.example.com'
        assert str(fsm.CACHE_DIR) == cache_dir
        assert fsm.TEST_ALL_BROWSERS is True
        assert fsm.CHECK_PROCESSES is True
        assert fsm.VERBOSE is True
        
        print("  ✓ Configuration from environment variables works correctly")
        return True
    except Exception as e:
        print(f"  ✗ Configuration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Full Smoke Test - Unit Test Suite")
    print("=" * 60)
    print()
    
    results = []
    
    try:
        results.append(test_imports())
        results.append(test_log_function())
        results.append(test_record_test_function())
        results.append(test_check_python_version())
        results.append(test_check_process_alive())
        results.append(test_filesystem_operations())
        results.append(test_script_downloader_test())
        results.append(test_environment_variables_test())
        results.append(test_report_generation())
        results.append(test_configuration_from_env())
        
        print()
        print("=" * 60)
        passed = sum(results)
        total = len(results)
        print(f"Test Results: {passed}/{total} passed")
        print("=" * 60)
        
        if all(results):
            print("✓ All tests passed successfully!")
            return 0
        else:
            print(f"✗ {total - passed} test(s) failed!")
            return 1
            
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
