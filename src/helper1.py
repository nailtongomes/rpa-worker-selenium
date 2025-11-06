#!/usr/bin/env python3
"""
Helper Script 1 - URL Validator
Basic sample helper script for smoke test expansion.
"""


def validate_url(url):
    """
    Validate if a URL has a proper format.
    
    Args:
        url: URL string to validate
        
    Returns:
        bool: True if URL is valid, False otherwise
    """
    if not url:
        return False
    
    # Basic URL validation
    if not (url.startswith('http://') or url.startswith('https://')):
        return False
    
    return True


def normalize_url(url):
    """
    Normalize URL by removing trailing slashes.
    
    Args:
        url: URL string to normalize
        
    Returns:
        str: Normalized URL
    """
    if not url:
        return url
    
    # Remove trailing slash
    if url.endswith('/'):
        return url.rstrip('/')
    
    return url


if __name__ == "__main__":
    # Test the helper functions
    test_urls = [
        'https://example.com',
        'http://example.com/',
        'example.com',
        '',
        'https://www.n3wizards.com/index/'
    ]
    
    print("[helper1] URL Validator Helper")
    for url in test_urls:
        is_valid = validate_url(url)
        normalized = normalize_url(url)
        print(f"  URL: {url!r} -> Valid: {is_valid}, Normalized: {normalized!r}")
