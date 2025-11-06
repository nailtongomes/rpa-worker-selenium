#!/usr/bin/env python3
"""
Helper Script 2 - Text Processor
Basic sample helper script for smoke test expansion.
"""

import re


def extract_domain(url):
    """
    Extract domain from URL.
    
    Args:
        url: URL string
        
    Returns:
        str: Domain extracted from URL or empty string
    """
    if not url:
        return ''
    
    # Extract domain using regex
    pattern = r'https?://([^/]+)'
    match = re.search(pattern, url)
    
    if match:
        return match.group(1)
    
    return ''


def clean_text(text):
    """
    Clean text by removing extra whitespace.
    
    Args:
        text: Text string to clean
        
    Returns:
        str: Cleaned text
    """
    if not text:
        return text
    
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', text)
    
    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()
    
    return cleaned


def format_report(url, title, status="success"):
    """
    Format a simple test report.
    
    Args:
        url: URL that was tested
        title: Title extracted from the page
        status: Test status (default: "success")
        
    Returns:
        str: Formatted report string
    """
    domain = extract_domain(url)
    report = f"""
Test Report
-----------
Domain: {domain}
URL: {url}
Title: {title}
Status: {status}
"""
    return report.strip()


if __name__ == "__main__":
    # Test the helper functions
    test_url = 'https://example.com/test'
    test_title = '  Example   Domain  '
    
    print("[helper2] Text Processor Helper")
    print(f"  Domain: {extract_domain(test_url)!r}")
    print(f"  Clean Title: {clean_text(test_title)!r}")
    print("\n" + format_report(test_url, clean_text(test_title)))
