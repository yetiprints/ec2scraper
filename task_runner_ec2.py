import boto3
import time
import logging
import json
import os
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class TaskRunner:
    def __init__(self):
        self.ec2 = boto3.client('ec2', region_name='eu-west-2')
        self.logs = boto3.client('logs', region_name='eu-west-2')
        self.CONFIG = {
            'security_group_id': 'sg-0baac2c985b88fd23',
            'subnet_id': 'subnet-0d00b3a1ba2dd811b',
            'log_group': '/aws/ec2/selenium-scraper'
        }

    def get_cloudwatch_config(self):
        """Get CloudWatch agent configuration"""
        instance_id = "$(curl -s http://169.254.169.254/latest/meta-data/instance-id)"
        config = {
            "agent": {
                "metrics_collection_interval": 60,
                "run_as_user": "root"
            },
            "logs": {
                "logs_collected": {
                    "files": {
                        "collect_list": [
                            {
                                "file_path": "/var/log/user-data.log",
                                "log_group_name": "/aws/ec2/selenium-scraper",
                                "log_stream_name": "{instance_id}/user-data",
                                "timezone": "UTC"
                            },
                            {
                                "file_path": "/tmp/chromedriver.log",
                                "log_group_name": "/aws/ec2/selenium-scraper",
                                "log_stream_name": "{instance_id}/chromedriver",
                                "timezone": "UTC"
                            }
                        ]
                    }
                }
            }
        }
        return json.dumps(config)

    def get_user_data(self):
        """Get user data script with proper escaping"""
        try:
            with open('simple_test.py', 'r') as f:
                test_code = f.read()
            
            cloudwatch_config = self.get_cloudwatch_config()
            
            return f'''#!/bin/bash
# Enable immediate output logging
exec 1> >(tee -a /var/log/user-data.log) 2>&1
set -x  # Enable command tracing

# Wait for instance to fully initialize
sleep 10

# Install required packages
apt-get update
apt-get install -y wget unzip python3-pip curl

# Install system dependencies for Chrome
apt-get install -y fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
    libcairo2 libcups2 libdbus-1-3 libdrm2 libgbm1 libgdk-pixbuf2.0-0 libgtk-3-0 libnspr4 \
    libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 xdg-utils libu2f-udev libvulkan1 libxkbcommon0 libxss1

# Install AWS CLI
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing AWS CLI..."
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
./aws/install

# Set region
export AWS_DEFAULT_REGION=eu-west-2

# Install CloudWatch agent
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing CloudWatch agent..."
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
dpkg -i -E ./amazon-cloudwatch-agent.deb

# Configure CloudWatch agent
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring CloudWatch agent..."
mkdir -p /opt/aws/amazon-cloudwatch-agent/bin/
cat > /opt/aws/amazon-cloudwatch-agent/bin/config.json << 'EOF'
{cloudwatch_config}
EOF

# Start CloudWatch agent
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting CloudWatch agent..."
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/bin/config.json
systemctl start amazon-cloudwatch-agent

# Create chrome user and directories
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating chrome user and directories..."
useradd -m -d /home/chrome -s /bin/bash chrome
mkdir -p /home/chrome /tmp/chrome-data /opt/chrome /opt/chrome-driver
chown -R chrome:chrome /home/chrome /tmp/chrome-data /opt/chrome /opt/chrome-driver

# Create log files with proper permissions
touch /tmp/chromedriver.log
chown chrome:chrome /tmp/chromedriver.log
chmod 644 /tmp/chromedriver.log

# Install Chrome for Testing
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing Chrome..."
cd /opt/chrome
wget https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/131.0.6778.108/linux64/chrome-linux64.zip
unzip chrome-linux64.zip
rm chrome-linux64.zip
chown -R chrome:chrome /opt/chrome

# Install ChromeDriver
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing ChromeDriver..."
cd /opt/chrome-driver
wget https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/131.0.6778.108/linux64/chromedriver-linux64.zip
unzip chromedriver-linux64.zip
rm chromedriver-linux64.zip
chown -R chrome:chrome /opt/chrome-driver

# Add to PATH for all users
echo 'export PATH=$PATH:/opt/chrome/chrome-linux64:/opt/chrome-driver/chromedriver-linux64' >> /etc/environment
source /etc/environment

# Install Python packages
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing Python packages..."
pip install selenium==4.15.2

# Copy test script
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Setting up test script..."
cat > /home/chrome/test.py << 'INNEREOF'
{test_code}
INNEREOF

# Set permissions
chown -R chrome:chrome /home/chrome/test.py
chmod +x /home/chrome/test.py

# Run test as chrome user with proper environment
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting test..."
sudo -u chrome bash -c "source /etc/environment && python3 /home/chrome/test.py"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Test finished!"
'''
        except Exception as e:
            logger.error(f"Failed to generate user data: {str(e)}", exc_info=True)
            raise

    def ensure_log_group_exists(self):
        """Ensure CloudWatch log group exists"""
        try:
            self.logs.create_log_group(logGroupName=self.CONFIG['log_group'])
            logger.info(f"Created log group: {self.CONFIG['log_group']}")
        except self.logs.exceptions.ResourceAlreadyExistsException:
            logger.info(f"Log group already exists: {self.CONFIG['log_group']}")

    def launch_instance(self):
        """Launch EC2 instance with Chrome"""
        try:
            # Get user data script
            user_data = self.get_user_data()
            
            # Request spot instance
            spot_price = '0.0416'  # Max price for t3.medium spot instance
            
            # Launch spot instance
            response = self.ec2.run_instances(
                ImageId='ami-003c3655bc8e97ae1',  # Ubuntu 22.04 LTS
                InstanceType='t3.medium',
                MinCount=1,
                MaxCount=1,
                InstanceMarketOptions={
                    'MarketType': 'spot',
                    'SpotOptions': {
                        'MaxPrice': spot_price,
                        'SpotInstanceType': 'one-time'
                    }
                },
                UserData=user_data,
                IamInstanceProfile={'Name': 'venue-scraper-profile'},
                SecurityGroups=['default'],
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': [
                            {
                                'Key': 'Name',
                                'Value': 'selenium-scraper'
                            }
                        ]
                    }
                ]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            logger.info(f"Launched instance {instance_id}")
            
            # Wait for instance to be running
            logger.info("Waiting for instance to be running...")
            waiter = self.ec2.get_waiter('instance_running')
            waiter.wait(InstanceIds=[instance_id])
            
            # Get instance public IP
            instance = self.ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
            public_ip = instance['PublicIpAddress']
            logger.info(f"Instance {instance_id} is running at {public_ip}")
            
            # Log CloudWatch URL
            logger.info(f"View logs at: https://eu-west-2.console.aws.amazon.com/cloudwatch/home?region=eu-west-2#logsV2:log-groups/log-group//aws/ec2/selenium-scraper")
            
            return instance_id
            
        except Exception as e:
            logger.error(f"Failed to launch instance: {str(e)}", exc_info=True)
            raise

    def wait_for_instance(self, instance_id):
        logger.info("Waiting for instance to be running...")
        waiter = self.ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])
        
        response = self.ec2.describe_instances(InstanceIds=[instance_id])
        return response['Reservations'][0]['Instances'][0]['PublicIpAddress']

    def tail_cloudwatch_logs(self, instance_id):
        """Stream CloudWatch logs for the instance"""
        try:
            seen_events = set()
            while True:
                # Get logs from all streams for this instance
                response = self.logs.describe_log_streams(
                    logGroupName=self.CONFIG['log_group'],
                    logStreamNamePrefix=instance_id
                )
                
                for stream in response.get('logStreams', []):
                    stream_name = stream['logStreamName']
                    
                    # Get log events
                    log_response = self.logs.get_log_events(
                        logGroupName=self.CONFIG['log_group'],
                        logStreamName=stream_name,
                        startFromHead=True
                    )
                    
                    for event in log_response['events']:
                        event_id = f"{stream_name}:{event['timestamp']}"
                        if event_id not in seen_events:
                            print(f"[{stream_name}] {event['message']}")
                            seen_events.add(event_id)
                
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Stopped tailing logs")

    def run(self):
        try:
            # Ensure log group exists
            self.ensure_log_group_exists()
            
            # Launch instance
            instance_id = self.launch_instance()
            if not instance_id:
                return
            
            ip_address = self.wait_for_instance(instance_id)
            logger.info(f"Instance {instance_id} is running at {ip_address}")
            logger.info(f"View logs at: https://eu-west-2.console.aws.amazon.com/cloudwatch/home?region=eu-west-2#logsV2:log-groups/log-group/{self.CONFIG['log_group']}")
            
            # Stream logs
            self.tail_cloudwatch_logs(instance_id)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    runner = TaskRunner()
    runner.run()
