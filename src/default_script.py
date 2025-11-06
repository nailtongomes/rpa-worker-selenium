#!/usr/bin/env python3
"""
Default Script - Sample Main Script
Simulates a downloaded script that uses helper modules.
This is used for smoke test to simulate the download scenario.
"""

import sys
import os
from pathlib import Path

# Add /app/src to path if running in Docker environment
if os.path.exists('/app/src'):
    sys.path.insert(0, '/app/src')


def main():
    """
    Main function that demonstrates using helper scripts.
    """
    print("[default_script] Starting default script execution")
    
    # Try to import and use helper scripts
    try:
        import helper1
        import helper2
        
        test_url = 'https://example.com/test'
        test_title = '  Example   Test   Page  '
        
        print("[default_script] Using helper1 to validate URL")
        is_valid = helper1.validate_url(test_url)
        normalized = helper1.normalize_url(test_url)
        print(f"[default_script] URL valid: {is_valid}, Normalized: {normalized}")
        
        print("[default_script] Using helper2 to process text")
        domain = helper2.extract_domain(test_url)
        clean_title = helper2.clean_text(test_title)
        print(f"[default_script] Domain: {domain}, Clean title: {clean_title}")
        
        print("[default_script] Generating report")
        report = helper2.format_report(test_url, clean_title, "success")
        print(report)
        
        print("[default_script] ✓ Successfully used helper scripts")
        return 0
        
    except ImportError as e:
        print(f"[default_script] Warning: Could not import helper scripts: {e}")
        print("[default_script] This is expected if helpers are not in /app/src")
        return 0
    except Exception as e:
        print(f"[default_script] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
