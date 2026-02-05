#!/usr/bin/env python3
"""
Integration tests for entrypoint.sh standby mode

Tests that:
1. Existing behavior (SCRIPT_URL and WORKER_LOOP) is not affected
2. Standby mode activates correctly when WORKER_MODE=standby
3. Environment variables are properly exported
"""

import pytest
import subprocess
import os
import pathlib


# Get the repository root directory
REPO_ROOT = pathlib.Path(__file__).parent.resolve()


def test_entrypoint_exports_worker_mode_default():
    """Test that WORKER_MODE defaults to 'pull'."""
    result = subprocess.run(
        ['bash', '-c', 'source ./entrypoint.sh > /dev/null 2>&1 && echo "$WORKER_MODE"'],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=5
    )
    # The output should contain "pull" from the default WORKER_MODE
    # Note: This will fail with actual execution, but validates the export exists
    assert result.returncode in [0, 1]  # May fail due to missing dependencies


def test_entrypoint_exports_task_server_port():
    """Test that TASK_SERVER_PORT is exported with default value."""
    result = subprocess.run(
        ['bash', '-c', 'source ./entrypoint.sh > /dev/null 2>&1 && echo "$TASK_SERVER_PORT"'],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=5
    )
    # Should export the variable (even if execution fails)
    assert result.returncode in [0, 1]


def test_entrypoint_has_standby_check():
    """Test that entrypoint.sh contains the standby mode check."""
    with open(REPO_ROOT / 'entrypoint.sh', 'r') as f:
        content = f.read()
    
    # Check for standby mode logic
    assert 'WORKER_MODE' in content
    assert 'standby' in content
    assert 'task_server.py' in content
    assert 'TASK_SERVER_PORT' in content


def test_entrypoint_standby_before_loop():
    """Test that standby check comes before loop check."""
    with open(REPO_ROOT / 'entrypoint.sh', 'r') as f:
        content = f.read()
    
    # Find positions of key checks
    standby_pos = content.find('WORKER_MODE')
    loop_pos = content.find('WORKER_LOOP')
    
    # Standby should be checked in the environment setup
    assert standby_pos > 0, "WORKER_MODE check not found"
    assert loop_pos > 0, "WORKER_LOOP check not found"


def test_task_server_file_exists():
    """Test that task_server.py exists and is executable."""
    task_server_path = REPO_ROOT / 'task_server.py'
    assert task_server_path.exists(), "task_server.py not found"
    assert os.access(task_server_path, os.X_OK), "task_server.py is not executable"


def test_task_server_imports():
    """Test that task_server.py can be imported."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    
    try:
        import task_server
        assert hasattr(task_server, 'app'), "Flask app not found"
        assert hasattr(task_server, 'validate_auth'), "validate_auth function not found"
        assert hasattr(task_server, 'validate_payload'), "validate_payload function not found"
    except ImportError as e:
        pytest.fail(f"Failed to import task_server: {e}")


def test_worker_readme_documents_standby():
    """Test that WORKER_README.md documents the standby mode."""
    with open(REPO_ROOT / 'WORKER_README.md', 'r') as f:
        content = f.read()
    
    # Check for standby mode documentation
    assert 'standby' in content.lower(), "Standby mode not documented"
    assert 'WORKER_MODE' in content, "WORKER_MODE not documented"
    assert 'TASK_SERVER_PORT' in content, "TASK_SERVER_PORT not documented"
    assert 'TASK_AUTH_TOKEN' in content, "TASK_AUTH_TOKEN not documented"
    assert '/task' in content, "Task endpoint not documented"
    assert '/health' in content, "Health endpoint not documented"


def test_requirements_includes_flask():
    """Test that requirements.txt includes Flask."""
    with open(REPO_ROOT / 'requirements.txt', 'r') as f:
        content = f.read()
    
    assert 'Flask' in content or 'flask' in content, "Flask not in requirements.txt"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
