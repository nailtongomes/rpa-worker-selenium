#!/usr/bin/env python3
"""
Test script for RPA Worker Selenium features.
Tests the script downloader and smoke test functionality.
"""

import os
import sys
import tempfile
import pathlib
from unittest.mock import patch, MagicMock


def test_script_downloader():
    """Test script downloader functionality."""
    print("Testing script_downloader.py...")
    
    from script_downloader import get_filename_from_url, download_helper_scripts
    
    # Test 1: Filename extraction
    test_cases = [
        ('https://example.com/script.py', 'script.py'),
        ('https://example.com/path/to/my_script.py', 'my_script.py'),
        ('https://raw.githubusercontent.com/user/repo/main/test.py', 'test.py'),
    ]
    
    for url, expected in test_cases:
        result = get_filename_from_url(url)
        assert result == expected, f"Failed: {url} -> {result} (expected {expected})"
        print(f"  ✓ get_filename_from_url('{url}') = '{result}'")
    
    # Test 2: Filename extraction for URL without .py extension
    url_no_ext = 'https://example.com/test'
    result = get_filename_from_url(url_no_ext)
    assert result.startswith('script_'), f"Failed: {url_no_ext} -> {result}"
    assert result.endswith('.py'), f"Failed: {url_no_ext} -> {result}"
    print(f"  ✓ get_filename_from_url('{url_no_ext}') = '{result}' (generated)")
    
    # Test 3: Helper URLs parsing
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test with empty string
        result = download_helper_scripts("", tmpdir)
        assert result == [], f"Failed: empty string should return []"
        print(f"  ✓ download_helper_scripts('', ...) = []")
        
        # Test with None
        result = download_helper_scripts(None, tmpdir)
        assert result == [], f"Failed: None should return []"
        print(f"  ✓ download_helper_scripts(None, ...) = []")
    
    print("✓ All script_downloader tests passed!\n")


def test_smoke_test_title_extraction():
    """Test smoke test title extraction logic."""
    print("Testing smoke_test.py title extraction...")
    
    # Set CACHE_DIR before importing to avoid permission issues
    temp_cache = tempfile.mkdtemp()
    os.environ['CACHE_DIR'] = temp_cache
    
    from smoke_test import extract_title_from_html
    
    # Test 1: Normal HTML with title
    html_with_title = '<html><head><title>Test Title</title></head><body>Test</body></html>'
    title = extract_title_from_html(html_with_title)
    assert title == "Test Title", f"Failed: got '{title}'"
    print(f"  ✓ Title extraction: 'Test Title'")
    
    # Test 2: HTML without title
    html_no_title = '<html><body>No title</body></html>'
    title = extract_title_from_html(html_no_title)
    assert title == "Desconhecido", f"Failed: got '{title}'"
    print(f"  ✓ No title case: 'Desconhecido'")
    
    # Test 3: HTML with empty title
    html_empty_title = '<html><head><title></title></head><body>Test</body></html>'
    title = extract_title_from_html(html_empty_title)
    assert title == "Desconhecido", f"Failed: got '{title}'"
    print(f"  ✓ Empty title case: 'Desconhecido'")
    
    # Test 4: HTML with whitespace in title
    html_whitespace = '<html><head><title>  Spaced  Title  </title></head><body>Test</body></html>'
    title = extract_title_from_html(html_whitespace)
    assert title == "Spaced Title", f"Failed: got '{title}'"
    print(f"  ✓ Whitespace title case: 'Spaced Title'")
    
    # Test 5: HTML with newlines in title
    html_newlines = '<html><head><title>Multi\nLine\nTitle</title></head><body>Test</body></html>'
    title = extract_title_from_html(html_newlines)
    assert title == "Multi Line Title", f"Failed: got '{title}'"
    print(f"  ✓ Newlines in title case: 'Multi Line Title'")
    
    # Test 6: HTML with case-insensitive title tag
    html_uppercase = '<html><head><TITLE>Uppercase Title</TITLE></head><body>Test</body></html>'
    title = extract_title_from_html(html_uppercase)
    assert title == "Uppercase Title", f"Failed: got '{title}'"
    print(f"  ✓ Case-insensitive title: 'Uppercase Title'")
    
    print("✓ All smoke_test title extraction tests passed!\n")


def test_environment_variables():
    """Test environment variable handling."""
    print("Testing environment variable handling...")
    
    # Test default values - use temp directory to avoid permission issues
    temp_cache = tempfile.mkdtemp()
    os.environ['CACHE_DIR'] = temp_cache
    os.environ.pop('TARGET_URL', None)
    os.environ.pop('SCRIPT_URL', None)
    
    # Import and check defaults
    import importlib
    import smoke_test
    importlib.reload(smoke_test)
    
    assert smoke_test.TARGET_URL == "https://www.n3wizards.com/index/", "Default TARGET_URL mismatch"
    print(f"  ✓ Default TARGET_URL: {smoke_test.TARGET_URL}")
    
    # Test custom values
    os.environ['TARGET_URL'] = 'https://example.com/test'
    custom_cache = tempfile.mkdtemp()
    os.environ['CACHE_DIR'] = custom_cache
    
    importlib.reload(smoke_test)
    
    assert smoke_test.TARGET_URL == "https://example.com/test", "Custom TARGET_URL mismatch"
    print(f"  ✓ Custom TARGET_URL: {smoke_test.TARGET_URL}")
    
    assert str(smoke_test.CACHE_DIR) == custom_cache, "Custom CACHE_DIR mismatch"
    print(f"  ✓ Custom CACHE_DIR: {smoke_test.CACHE_DIR}")
    
    print("✓ All environment variable tests passed!\n")


def test_brave_example_script():
    """Test Brave example script structure and configuration."""
    print("Testing example_script_brave.py...")
    
    # Test 1: Check script exists and is readable
    import pathlib
    script_path = pathlib.Path(__file__).parent / 'example_script_brave.py'
    assert script_path.exists(), "example_script_brave.py not found"
    print("  ✓ Script file exists")
    
    # Test 2: Parse the script without executing it
    import ast
    
    with open(script_path, 'r') as f:
        script_source = f.read()
    
    try:
        tree = ast.parse(script_source)
        print("  ✓ Script has valid Python syntax")
    except SyntaxError as e:
        raise AssertionError(f"Script has syntax error: {e}")
    
    # Test 3: Check for required functions
    function_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    
    assert 'create_brave_driver' in function_names, "Missing create_brave_driver function"
    print("  ✓ create_brave_driver function exists")
    
    assert 'example_automation' in function_names, "Missing example_automation function"
    print("  ✓ example_automation function exists")
    
    # Test 4: Verify the script has proper imports
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
    
    required_imports = ['selenium', 'sys', 'os']
    
    for imp in required_imports:
        # Check if import is present (either exact match or as part of module path)
        found = False
        for import_name in imports:
            if import_name and (imp == import_name or imp in import_name or import_name.startswith(imp + '.')):
                found = True
                break
        assert found, f"Missing import: {imp}"
    
    print("  ✓ All required imports present")
    
    # Test 5: Check that the script configures Brave binary location
    assert 'binary_location' in script_source, "Script should set binary_location for Brave"
    assert '/usr/bin/brave-browser' in script_source, "Script should reference Brave browser path"
    print("  ✓ Brave binary location configured correctly")
    
    # Test 6: Check for headless mode configuration
    assert '--headless' in script_source, "Script should configure headless mode"
    print("  ✓ Headless mode configuration present")
    
    print("✓ All Brave example script tests passed!\n")



def main():
    """Run all tests."""
    print("=" * 60)
    print("RPA Worker Selenium - Test Suite")
    print("=" * 60)
    print()
    
    try:
        test_script_downloader()
        test_smoke_test_title_extraction()
        test_environment_variables()
        test_brave_example_script()
        
        print("=" * 60)
        print("✓ All tests passed successfully!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
