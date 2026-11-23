#!/usr/bin/env python3
"""
Tests for task_server.py - HTTP Standby Mode

Tests the Flask server functionality including:
- Authentication validation
- Payload validation
- Task acceptance
- Error handling
"""

import pytest
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
from task_server import (
    validate_auth,
    validate_payload,
    app,
    TASK_AUTH_TOKEN
)


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


class TestHealthEndpoint:
    """Test the health check endpoint."""
    
    def test_health_check(self, client):
        """Test health endpoint returns 200 OK."""
        response = client.get('/health')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['mode'] == 'standby'
        assert 'timestamp' in data
        assert 'task_executing' in data


class TestPayloadValidation:
    """Test payload validation logic."""
    
    def test_valid_payload(self):
        """Test validation of a valid payload."""
        payload = {
            "script_url": "https://example.com/script_abc123.py",
            "script_name": "script_abc123.py",
            "payload": {"key": "value"}
        }
        valid, error = validate_payload(payload)
        assert valid is True
        assert error is None
    
    def test_missing_script_url(self):
        """Test validation fails when script_url is missing."""
        payload = {
            "script_name": "script.py"
        }
        valid, error = validate_payload(payload)
        assert valid is False
        assert "script_url" in error
    
    def test_missing_script_name(self):
        """Test validation fails when script_name is missing."""
        payload = {
            "script_url": "https://example.com/script.py"
        }
        valid, error = validate_payload(payload)
        assert valid is False
        assert "script_name" in error
    
    def test_non_https_url(self):
        """Test validation fails for non-HTTPS URLs."""
        payload = {
            "script_url": "http://example.com/script.py",
            "script_name": "script.py"
        }
        valid, error = validate_payload(payload)
        assert valid is False
        assert "HTTPS" in error
    
    def test_script_name_mismatch(self):
        """Test validation fails when script_name doesn't match URL."""
        payload = {
            "script_url": "https://example.com/script_abc.py",
            "script_name": "different_name.py"
        }
        valid, error = validate_payload(payload)
        assert valid is False
        assert "does not match" in error
    
    def test_invalid_payload_type(self):
        """Test validation fails when payload is not a dict."""
        payload = {
            "script_url": "https://example.com/script_abc.py",
            "script_name": "script_abc.py",
            "payload": "not a dict"
        }
        valid, error = validate_payload(payload)
        assert valid is False
        assert "JSON object" in error
    
    def test_empty_payload(self):
        """Test validation fails for empty payload."""
        valid, error = validate_payload(None)
        assert valid is False
        assert "Empty payload" in error


class TestAuthValidation:
    """Test authentication validation."""
    
    def test_no_auth_required_when_token_not_set(self, client):
        """Test auth passes when TASK_AUTH_TOKEN is not set."""
        with patch('task_server.TASK_AUTH_TOKEN', ''):
            with client.application.test_request_context():
                valid, error = validate_auth()
                assert valid is True
                assert error is None
    
    def test_valid_auth_token(self, client):
        """Test auth passes with valid token."""
        with patch('task_server.TASK_AUTH_TOKEN', 'secret-token'):
            with client.application.test_request_context(
                headers={'Authorization': 'Bearer secret-token'}
            ):
                valid, error = validate_auth()
                assert valid is True
                assert error is None
    
    def test_missing_auth_header(self, client):
        """Test auth fails when Authorization header is missing."""
        with patch('task_server.TASK_AUTH_TOKEN', 'secret-token'):
            with client.application.test_request_context():
                valid, error = validate_auth()
                assert valid is False
                assert "Authorization" in error
    
    def test_invalid_auth_token(self, client):
        """Test auth fails with invalid token."""
        with patch('task_server.TASK_AUTH_TOKEN', 'secret-token'):
            with client.application.test_request_context(
                headers={'Authorization': 'Bearer wrong-token'}
            ):
                valid, error = validate_auth()
                assert valid is False
                assert "Invalid" in error


class TestTaskEndpoint:
    """Test the /task endpoint."""
    
    def test_task_endpoint_requires_post(self, client):
        """Test that /task only accepts POST requests."""
        response = client.get('/task')
        assert response.status_code == 405  # Method Not Allowed
    
    def test_task_endpoint_invalid_json(self, client):
        """Test task endpoint rejects invalid JSON."""
        response = client.post(
            '/task',
            data='invalid json',
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
    
    @patch('task_server.TASK_AUTH_TOKEN', 'test-token')
    def test_task_endpoint_requires_auth(self, client):
        """Test task endpoint requires authentication when token is set."""
        payload = {
            "script_url": "https://example.com/script_abc.py",
            "script_name": "script_abc.py"
        }
        response = client.post(
            '/task',
            data=json.dumps(payload),
            content_type='application/json'
        )
        assert response.status_code == 401
    
    def test_task_endpoint_validates_payload(self, client):
        """Test task endpoint validates payload structure."""
        # Missing script_url
        payload = {"script_name": "script.py"}
        response = client.post(
            '/task',
            data=json.dumps(payload),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'script_url' in data['error']
    
    @patch('task_server.task_executing', True)
    def test_task_endpoint_rejects_concurrent_tasks(self, client):
        """Test task endpoint rejects concurrent tasks with 409 Conflict."""
        payload = {
            "script_url": "https://example.com/script_abc.py",
            "script_name": "script_abc.py"
        }
        response = client.post(
            '/task',
            data=json.dumps(payload),
            content_type='application/json'
        )
        assert response.status_code == 409
        data = json.loads(response.data)
        assert data['status'] == 'conflict'
    
    @patch('task_server.threading.Thread')
    @patch('task_server.task_executing', False)
    def test_task_endpoint_accepts_valid_task(self, mock_thread, client):
        """Test task endpoint accepts valid task and returns 202."""
        payload = {
            "script_url": "https://example.com/script_abc123.py",
            "script_name": "script_abc123.py",
            "payload": {"test": "data"}
        }
        
        response = client.post(
            '/task',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 202
        data = json.loads(response.data)
        assert data['status'] == 'accepted'
        assert data['script_url'] == payload['script_url']
        assert data['script_name'] == payload['script_name']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
