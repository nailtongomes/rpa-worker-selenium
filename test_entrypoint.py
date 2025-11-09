#!/usr/bin/env python3
"""
Test script to validate entrypoint.sh logic and environment variables
"""
import os
import subprocess
import sys

def run_bash_script_check(script_path):
    """Check if bash script has valid syntax"""
    try:
        result = subprocess.run(
            ['bash', '-n', script_path],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✓ {script_path} has valid bash syntax")
            return True
        else:
            print(f"✗ {script_path} has syntax errors:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"✗ Error checking {script_path}: {e}")
        return False

def check_dockerfile_args(dockerfile_path):
    """Check if Dockerfile has BUILD_PJEOFFICE argument"""
    try:
        with open(dockerfile_path, 'r') as f:
            content = f.read()
            if 'ARG BUILD_PJEOFFICE' in content:
                print(f"✓ {dockerfile_path} has BUILD_PJEOFFICE argument")
                return True
            else:
                print(f"✗ {dockerfile_path} missing BUILD_PJEOFFICE argument")
                return False
    except Exception as e:
        print(f"✗ Error reading {dockerfile_path}: {e}")
        return False

def check_dockerfile_env_vars(dockerfile_path):
    """Check if Dockerfile has USE_PJEOFFICE environment variable"""
    try:
        with open(dockerfile_path, 'r') as f:
            content = f.read()
            if 'USE_PJEOFFICE' in content:
                print(f"✓ {dockerfile_path} has USE_PJEOFFICE environment variable")
                return True
            else:
                print(f"✗ {dockerfile_path} missing USE_PJEOFFICE environment variable")
                return False
    except Exception as e:
        print(f"✗ Error reading {dockerfile_path}: {e}")
        return False

def check_dockerfile_pjeoffice_install(dockerfile_path):
    """Check if Dockerfile has conditional PJeOffice installation"""
    try:
        with open(dockerfile_path, 'r') as f:
            content = f.read()
            if 'pje-office.pje.jus.br' in content and 'if [ "$BUILD_PJEOFFICE"' in content:
                print(f"✓ {dockerfile_path} has conditional PJeOffice installation")
                return True
            else:
                print(f"✗ {dockerfile_path} missing conditional PJeOffice installation")
                return False
    except Exception as e:
        print(f"✗ Error reading {dockerfile_path}: {e}")
        return False

def check_entrypoint_functions(entrypoint_path):
    """Check if entrypoint.sh has required functions"""
    required_functions = [
        'setup_directories',
        'handle_sigterm',
        'start_xvfb',
        'start_openbox',
        'start_pjeoffice'
    ]
    
    try:
        with open(entrypoint_path, 'r') as f:
            content = f.read()
            all_found = True
            for func in required_functions:
                if f'{func}()' in content:
                    print(f"  ✓ Function {func} found")
                else:
                    print(f"  ✗ Function {func} not found")
                    all_found = False
            return all_found
    except Exception as e:
        print(f"✗ Error reading {entrypoint_path}: {e}")
        return False

def check_entrypoint_env_checks(entrypoint_path):
    """Check if entrypoint.sh checks environment variables"""
    env_vars = ['USE_XVFB', 'USE_OPENBOX', 'USE_PJEOFFICE']
    
    try:
        with open(entrypoint_path, 'r') as f:
            content = f.read()
            all_found = True
            for var in env_vars:
                if var in content:
                    print(f"  ✓ Environment variable {var} is checked")
                else:
                    print(f"  ✗ Environment variable {var} not checked")
                    all_found = False
            return all_found
    except Exception as e:
        print(f"✗ Error reading {entrypoint_path}: {e}")
        return False

def check_pjeoffice_env_vars(entrypoint_path):
    """Check if entrypoint.sh defines PJeOffice path environment variables"""
    pjeoffice_env_vars = ['PJEOFFICE_CONFIG_DIR', 'PJEOFFICE_CONFIG_FILE', 'PJEOFFICE_EXECUTABLE']
    
    try:
        with open(entrypoint_path, 'r') as f:
            content = f.read()
            all_found = True
            for var in pjeoffice_env_vars:
                if var in content:
                    print(f"  ✓ PJeOffice environment variable {var} is defined")
                else:
                    print(f"  ✗ PJeOffice environment variable {var} not defined")
                    all_found = False
            return all_found
    except Exception as e:
        print(f"✗ Error reading {entrypoint_path}: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Dockerfile and entrypoint.sh changes")
    print("=" * 60)
    
    results = []
    
    # Test entrypoint.sh
    print("\n1. Testing entrypoint.sh syntax...")
    results.append(run_bash_script_check('entrypoint.sh'))
    
    print("\n2. Testing entrypoint.sh functions...")
    results.append(check_entrypoint_functions('entrypoint.sh'))
    
    print("\n3. Testing entrypoint.sh environment variable checks...")
    results.append(check_entrypoint_env_checks('entrypoint.sh'))
    
    print("\n4. Testing entrypoint.sh PJeOffice path environment variables...")
    results.append(check_pjeoffice_env_vars('entrypoint.sh'))
    
    # Test Dockerfiles
    dockerfiles = ['Dockerfile', 'Dockerfile.chrome', 'Dockerfile.firefox', 'Dockerfile.brave']
    
    for dockerfile in dockerfiles:
        print(f"\n5. Testing {dockerfile}...")
        print(f"   a. Checking BUILD_PJEOFFICE argument...")
        results.append(check_dockerfile_args(dockerfile))
        
        print(f"   b. Checking USE_PJEOFFICE environment variable...")
        results.append(check_dockerfile_env_vars(dockerfile))
        
        print(f"   c. Checking conditional PJeOffice installation...")
        results.append(check_dockerfile_pjeoffice_install(dockerfile))
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    
    if all(results):
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed!")
        return 1

if __name__ == '__main__':
    sys.exit(main())
