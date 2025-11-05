#!/usr/bin/env python3
"""
Example Selenium script for RPA automation tasks.
This script demonstrates how to use Selenium in headless mode.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys


def create_driver():
    """Create and configure a Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def example_automation():
    """Example automation task: fetch page title."""
    driver = None
    try:
        print("Initializing Chrome WebDriver...")
        driver = create_driver()
        
        print("Navigating to example.com...")
        driver.get("https://example.com")
        
        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
        
        # Get page title and heading
        title = driver.title
        heading = driver.find_element(By.TAG_NAME, "h1").text
        
        print(f"Page Title: {title}")
        print(f"Page Heading: {heading}")
        print("✓ Automation completed successfully!")
        
        return True
        
    except Exception as e:
        print(f"✗ Error during automation: {e}")
        return False
        
    finally:
        if driver:
            driver.quit()
            print("WebDriver closed.")


if __name__ == "__main__":
    success = example_automation()
    sys.exit(0 if success else 1)
