#!/usr/bin/env python3
"""
Example Selenium script for Firefox browser
This demonstrates basic usage of Selenium with Firefox in the rpa-worker-selenium container
"""

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

def main():
    # Configure Firefox options
    firefox_options = Options()
    firefox_options.add_argument('--headless')  # Run in headless mode
    firefox_options.add_argument('--no-sandbox')
    firefox_options.add_argument('--disable-dev-shm-usage')
    
    # Create service with explicit geckodriver path
    service = Service('/usr/local/bin/geckodriver')
    
    # Create driver
    print("Starting Firefox browser...")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    
    try:
        # Navigate to a website
        print("Navigating to example.com...")
        driver.get("https://example.com")
        
        # Get page title
        title = driver.title
        print(f"Page title: {title}")
        
        # Get page source length
        page_source_length = len(driver.page_source)
        print(f"Page source length: {page_source_length} characters")
        
        # Verify we got to the right page
        if "Example Domain" in title:
            print("✓ Successfully loaded example.com with Firefox!")
        else:
            print("✗ Unexpected page title")
            
    except Exception as e:
        print(f"Error occurred: {e}")
        raise
    finally:
        # Clean up
        print("Closing browser...")
        driver.quit()
        print("Done!")

if __name__ == "__main__":
    main()
