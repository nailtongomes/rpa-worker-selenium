#!/usr/bin/env python3
"""
Example script that can be downloaded and executed.
This demonstrates the SCRIPT_URL functionality.
"""

import sys
import datetime

def main():
    print("=" * 60)
    print("Example Downloaded Script Execution")
    print("=" * 60)
    print(f"Timestamp: {datetime.datetime.now().isoformat()}")
    print("This script was downloaded and executed via SCRIPT_URL!")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
