# rpa-worker-selenium

A Docker image for running dynamic Python scripts with Selenium automation. This image comes pre-configured with Chrome, ChromeDriver, and all necessary dependencies for web automation tasks.

## Features

- 🐍 Python 3.11
- 🌐 Selenium WebDriver
- 🚀 Google Chrome (headless mode supported)
- 📦 ChromeDriver (automatically matched to Chrome version)
- 🔧 Pre-configured for RPA and automation tasks
- 📊 Additional packages: requests, beautifulsoup4, pandas, openpyxl, and more

## Quick Start

### Building the Docker Image

```bash
git clone https://github.com/nailtongomes/rpa-worker-selenium.git
cd rpa-worker-selenium
docker build -t rpa-worker-selenium .
```

### Running the Example Script

```bash
docker run --rm rpa-worker-selenium example_script.py
```

### Running Your Own Scripts

#### Option 1: Mount a script from your local machine

```bash
docker run --rm -v $(pwd)/my_script.py:/app/scripts/my_script.py rpa-worker-selenium /app/scripts/my_script.py
```

#### Option 2: Build the script into the image

1. Place your script in the repository directory
2. Rebuild the image
3. Run the container with your script:

```bash
docker run --rm rpa-worker-selenium your_script.py
```

#### Option 3: Use the helper script

```bash
docker run --rm -v $(pwd)/my_script.py:/app/scripts/my_script.py rpa-worker-selenium bash run_script.sh /app/scripts/my_script.py
```

## Writing Selenium Scripts

Here's a minimal example of a Selenium script:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Configure Chrome options
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# Create driver
driver = webdriver.Chrome(options=chrome_options)

# Your automation code
driver.get("https://example.com")
print(driver.title)

# Clean up
driver.quit()
```

## Advanced Usage

### Interactive Python Shell

```bash
docker run --rm -it rpa-worker-selenium
```

### Run with Environment Variables

```bash
docker run --rm -e MY_VAR=value rpa-worker-selenium my_script.py
```

### Access Container Shell

```bash
docker run --rm -it rpa-worker-selenium bash
```

## Installed Python Packages

- selenium >= 4.15.0
- requests >= 2.31.0
- beautifulsoup4 >= 4.12.0
- lxml >= 4.9.0
- pandas >= 2.1.0
- openpyxl >= 3.1.0
- pillow >= 10.1.0

## Customization

### Adding More Python Packages

Edit `requirements.txt` and rebuild the image:

```bash
echo "your-package>=1.0.0" >> requirements.txt
docker build -t rpa-worker-selenium .
```

### Changing Python Version

Edit the first line of `Dockerfile`:

```dockerfile
FROM python:3.12-slim  # or any other version
```

## Troubleshooting

### Chrome/ChromeDriver Version Mismatch

The Dockerfile automatically installs the correct ChromeDriver version for the installed Chrome. If you encounter issues, rebuild the image:

```bash
docker build --no-cache -t rpa-worker-selenium .
```

### Memory Issues

If you encounter memory issues, increase Docker's memory limit or add this to your Chrome options:

```python
chrome_options.add_argument('--disable-dev-shm-usage')
```

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.