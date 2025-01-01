# EC2 Selenium Scraper

A Python-based web scraping framework that runs Selenium on EC2 spot instances with CloudWatch logging.

## Features

- Runs on t3.medium EC2 spot instances for cost efficiency
- Uses Chrome in headless mode
- Automatic setup of Chrome, ChromeDriver, and all dependencies
- CloudWatch logging integration
- Proper error handling and logging
- Screenshot capture capability

## Setup

1. Ensure you have AWS credentials configured with appropriate permissions:
   - EC2 (spot instances)
   - CloudWatch
   - IAM

2. Required IAM Role: `venue-scraper-role` with policies:
   - CloudWatchAgentServerPolicy
   - AmazonS3FullAccess

3. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Basic test (visits GitHub and captures title):
```bash
python task_runner_ec2.py
```

2. View logs in CloudWatch:
- Log group: `/aws/ec2/selenium-scraper`
- Streams: 
  - `{instance-id}/chromedriver` - Chrome and Selenium logs
  - `{instance-id}/user-data` - Instance setup logs

## Files

- `task_runner_ec2.py` - Main script for launching EC2 instances
- `simple_test.py` - Sample scraper that visits GitHub
- `requirements.txt` - Python dependencies
