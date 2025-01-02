from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import boto3
import logging
import sys
import json
import requests
from datetime import datetime

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

def update_location_status(country_code, location_name, status, error_message=None):
    """Update location status in DynamoDB"""
    try:
        # Get credentials from instance metadata
        session = boto3.Session(region_name='eu-west-2')
        dynamodb = session.client('dynamodb')
        
        update_expr = "SET #status = :status, last_updated = :timestamp"
        expr_attrs = {
            ':status': {'S': status},
            ':timestamp': {'S': datetime.utcnow().isoformat()}
        }
        expr_names = {'#status': 'status'}
        
        if error_message:
            update_expr += ", error_message = :error"
            expr_attrs[':error'] = {'S': error_message}
        
        dynamodb.update_item(
            TableName='dental_location_control',
            Key={
                'country_code': {'S': country_code},
                'location_name': {'S': location_name}
            },
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_attrs
        )
        logger.info(f"Updated location {country_code}:{location_name} status to {status}")
    except Exception as e:
        logger.error(f"Failed to update DynamoDB: {str(e)}", exc_info=True)

def terminate_instance():
    """Terminate the current instance"""
    try:
        # Get instance ID from metadata
        instance_id = requests.get(
            'http://169.254.169.254/latest/meta-data/instance-id',
            timeout=2
        ).text
        
        # Get credentials from instance metadata
        session = boto3.Session(region_name='eu-west-2')
        ec2 = session.client('ec2')
        
        ec2.terminate_instances(InstanceIds=[instance_id])
        logger.info(f"Initiated termination of instance {instance_id}")
    except Exception as e:
        logger.error(f"Failed to terminate instance: {str(e)}", exc_info=True)
        sys.exit(1)

def run_test(country_code, location_name):
    try:
        logger.info(f"Starting test for {country_code}:{location_name}")
        
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
        
        # Update DynamoDB and terminate
        update_location_status(country_code, location_name, 'COMPLETE')
        terminate_instance()
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Test failed: {error_msg}", exc_info=True)
        update_location_status(country_code, location_name, 'STOPPED', error_msg)
        terminate_instance()

if __name__ == "__main__":
    # Get location from command line args
    if len(sys.argv) != 3:
        logger.error("Usage: python simple_test.py <country_code> <location_name>")
        sys.exit(1)
    
    country_code = sys.argv[1]
    location_name = sys.argv[2]
    run_test(country_code, location_name)
