from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import logging
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/chromedriver.log')
    ]
)
logger = logging.getLogger(__name__)

def run_test():
    try:
        logger.info("Setting up Chrome options...")
        options = Options()
        options.add_argument('--verbose')
        options.add_argument('--log-level=0')
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--remote-debugging-port=9222')
        options.add_argument('--user-data-dir=/tmp/chrome-data')
        
        logger.info("Starting Chrome...")
        driver = webdriver.Chrome(options=options)
        
        logger.info("Visiting GitHub...")
        driver.get("https://github.com")
        
        logger.info(f"Success! Page title: {driver.title}")
        driver.save_screenshot('/tmp/github.png')
        logger.info("Saved screenshot to /tmp/github.png")
        
        driver.quit()
        logger.info("Test completed successfully")
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_test()
