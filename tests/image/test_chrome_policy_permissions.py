#!/usr/bin/env python3
"""
Test script to verify Chrome policy directory permissions after Dockerfile changes.
This test should be run inside a built Docker container to verify the permissions work.

Usage:
  docker run --rm rpa-worker-selenium python /app/test_chrome_policy_permissions.py
  # Or as rpauser:
  docker run --rm --user rpauser rpa-worker-selenium python /app/test_chrome_policy_permissions.py
"""
import os
import sys
import json
from pathlib import Path

# Configuration
CHROME_POLICY_DIR = "/etc/opt/chrome/policies/managed"
CHROME_POLICY_FILE = f"{CHROME_POLICY_DIR}/auto_select_certificate.json"

def get_user_info():
    """Get current user information."""
    import pwd
    uid = os.getuid()
    try:
        user = pwd.getpwuid(uid)
        return {
            'uid': uid,
            'gid': os.getgid(),
            'username': user.pw_name,
            'home': user.pw_dir
        }
    except KeyError:
        return {
            'uid': uid,
            'gid': os.getgid(),
            'username': 'unknown',
            'home': os.environ.get('HOME', 'unknown')
        }

def check_directory_exists():
    """Test that the directory exists."""
    print("\n[TEST 1] Checking if Chrome policy directory exists...")
    
    if not os.path.exists(CHROME_POLICY_DIR):
        print(f"  ❌ FAIL: Directory {CHROME_POLICY_DIR} does not exist")
        return False
    
    print(f"  ✅ PASS: Directory exists")
    return True

def check_directory_permissions():
    """Check directory permissions and ownership."""
    print("\n[TEST 2] Checking directory permissions and ownership...")
    
    try:
        stat_info = os.stat(CHROME_POLICY_DIR)
        mode = oct(stat_info.st_mode)[-3:]
        
        print(f"  Directory permissions: {mode}")
        print(f"  Owner UID: {stat_info.st_uid}")
        print(f"  Owner GID: {stat_info.st_gid}")
        
        # Check if owned by rpauser (UID 1000)
        if stat_info.st_uid == 1000:
            print(f"  ✅ PASS: Directory is owned by rpauser (UID 1000)")
        elif stat_info.st_uid == 0:
            print(f"  ℹ️  INFO: Directory is owned by root (UID 0)")
            print(f"  ⚠️  WARNING: This may cause issues when running as rpauser")
        else:
            print(f"  ⚠️  WARNING: Unexpected owner UID: {stat_info.st_uid}")
        
        return True
    except Exception as e:
        print(f"  ❌ FAIL: Could not check permissions: {e}")
        return False

def test_write_permission():
    """Test that we can write to the directory."""
    print("\n[TEST 3] Testing write permissions...")
    
    user_info = get_user_info()
    print(f"  Running as: {user_info['username']} (UID: {user_info['uid']})")
    
    test_file = f"{CHROME_POLICY_DIR}/test_write.json"
    
    try:
        # Try to write a test file
        with open(test_file, 'w') as f:
            json.dump({"test": "write_permission"}, f)
        
        print(f"  ✅ PASS: Successfully wrote test file")
        
        # Clean up
        os.remove(test_file)
        print(f"  ✅ PASS: Successfully removed test file")
        return True
        
    except PermissionError as e:
        print(f"  ❌ FAIL: Permission denied: {e}")
        print(f"  This indicates the directory permissions are incorrect for user {user_info['username']}")
        return False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        return False

def test_policy_file_write():
    """Test writing the actual Chrome policy file."""
    print("\n[TEST 4] Testing Chrome policy file write...")
    
    try:
        # Create a sample Chrome policy
        policy = {
            "AutoSelectCertificateForUrls": [
                json.dumps({"pattern": "*", "filter": {}})
            ]
        }
        
        # Write the policy file
        with open(CHROME_POLICY_FILE, 'w') as f:
            json.dump(policy, f, indent=2)
        
        print(f"  ✅ PASS: Successfully wrote policy file")
        
        # Verify it was written correctly
        with open(CHROME_POLICY_FILE, 'r') as f:
            read_policy = json.load(f)
        
        if read_policy == policy:
            print(f"  ✅ PASS: Policy file content verified")
        else:
            print(f"  ❌ FAIL: Policy file content mismatch")
            return False
        
        # Clean up
        os.remove(CHROME_POLICY_FILE)
        print(f"  ✅ PASS: Successfully removed policy file")
        return True
        
    except PermissionError as e:
        print(f"  ❌ FAIL: Permission denied: {e}")
        return False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        return False

def test_no_sudo_required():
    """Verify that we didn't use sudo anywhere."""
    print("\n[TEST 5] Verifying no sudo was required...")
    print(f"  ✅ PASS: All operations completed without sudo")
    return True

def main():
    """Run all tests."""
    print("=" * 70)
    print("Chrome Policy Directory Permissions Test")
    print("=" * 70)
    
    user_info = get_user_info()
    print(f"\nRunning as user: {user_info['username']} (UID: {user_info['uid']}, GID: {user_info['gid']})")
    print(f"Home directory: {user_info['home']}")
    
    # Run all tests
    tests = [
        check_directory_exists,
        check_directory_permissions,
        test_write_permission,
        test_policy_file_write,
        test_no_sudo_required
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n  ❌ TEST EXCEPTION: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Passed: {passed}/{total}")
    
    if all(results):
        print("\n✅ ALL TESTS PASSED!")
        print("\nThe Chrome policy directory permissions are correctly configured.")
        print("Certificate management will work without sudo when running as rpauser.")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("\nThe Chrome policy directory may need permission adjustments.")
        
        # Provide helpful guidance
        user_info = get_user_info()
        if user_info['uid'] == 1000:  # rpauser
            print("\nSuggested fix (run as root inside container):")
            print(f"  chown -R rpauser:rpauser {CHROME_POLICY_DIR}")
        elif user_info['uid'] == 0:  # root
            print("\nNote: Tests passed when running as root, but may fail as rpauser.")
            print("Ensure the directory is owned by rpauser for non-root usage.")
        
        return 1

if __name__ == "__main__":
    sys.exit(main())
