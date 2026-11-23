#!/usr/bin/env python3
"""
Example: Sending tasks to RPA Worker in Standby Mode

This script demonstrates how to send task requests to a worker running in standby mode.
"""

import requests
import json
import time
import sys


class StandbyWorkerClient:
    """Client for interacting with RPA Worker in standby mode."""
    
    def __init__(self, base_url: str, auth_token: str = None):
        """
        Initialize the client.
        
        Args:
            base_url: Base URL of the worker (e.g., http://localhost:8080)
            auth_token: Optional Bearer token for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token
        self.headers = {'Content-Type': 'application/json'}
        
        if auth_token:
            self.headers['Authorization'] = f'Bearer {auth_token}'
    
    def health_check(self):
        """
        Check if the worker is healthy.
        
        Returns:
            dict: Health status response
        """
        try:
            response = requests.get(f'{self.base_url}/health', timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Health check failed: {e}")
            return None
    
    def send_task(self, script_url: str, script_name: str, payload: dict = None):
        """
        Send a task to the worker.
        
        Args:
            script_url: HTTPS URL of the Python script to execute
            script_name: Name of the script (must match URL filename)
            payload: Optional data to pass to the script
            
        Returns:
            dict: Task response
        """
        task_data = {
            'script_url': script_url,
            'script_name': script_name
        }
        
        if payload:
            task_data['payload'] = payload
        
        try:
            response = requests.post(
                f'{self.base_url}/task',
                headers=self.headers,
                json=task_data,
                timeout=10
            )
            
            if response.status_code == 202:
                print(f"✅ Task accepted: {response.json()}")
                return response.json()
            elif response.status_code == 409:
                print(f"⚠️  Another task is already executing")
                return None
            else:
                print(f"❌ Task rejected: {response.status_code}")
                print(f"   Response: {response.json()}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to send task: {e}")
            return None


def example_usage():
    """Example usage of the standby worker client."""
    
    # Configuration
    WORKER_URL = "http://localhost:8080"
    AUTH_TOKEN = None  # Set if TASK_AUTH_TOKEN is configured
    
    # Initialize client
    client = StandbyWorkerClient(WORKER_URL, AUTH_TOKEN)
    
    # 1. Check worker health
    print("1. Checking worker health...")
    health = client.health_check()
    if health:
        print(f"   Status: {health['status']}")
        print(f"   Mode: {health['mode']}")
        print(f"   Task executing: {health['task_executing']}")
    else:
        print("   Worker is not reachable")
        return 1
    print()
    
    # 2. Send a simple task
    print("2. Sending a simple task...")
    result = client.send_task(
        script_url="https://raw.githubusercontent.com/nailtongomes/rpa-worker-selenium/main/smoke_test.py",
        script_name="smoke_test.py"
    )
    
    if result:
        print(f"   Task ID: {result.get('script_name')}")
        print(f"   Status: {result.get('status')}")
    print()
    
    # Wait for task to complete (container will restart)
    print("3. Waiting for container to restart (takes ~5-10 seconds)...")
    time.sleep(10)
    
    # 4. Check health again (should be ready for new tasks)
    print("4. Checking worker health after restart...")
    health = client.health_check()
    if health:
        print(f"   Status: {health['status']}")
        print(f"   Task executing: {health['task_executing']}")
    print()
    
    # 5. Send a task with custom payload
    print("5. Sending a task with custom payload...")
    result = client.send_task(
        script_url="https://example.com/custom_script.py",
        script_name="custom_script.py",
        payload={
            "process_id": "12345",
            "action": "download_documents",
            "filters": {
                "start_date": "2024-01-01",
                "end_date": "2024-12-31"
            }
        }
    )
    
    if result:
        print(f"   Task accepted: {result.get('message')}")
    print()
    
    return 0


if __name__ == "__main__":
    print("=" * 60)
    print("RPA Worker Standby Mode - Example Client")
    print("=" * 60)
    print()
    
    sys.exit(example_usage())
