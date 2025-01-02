import boto3
import time
import logging
import json
import os
import signal
import sys
import requests
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
        self.dynamodb = boto3.client('dynamodb', region_name='eu-west-2')
        self.logs = boto3.client('logs', region_name='eu-west-2')
        self.running = True
        self.CONFIG = {
            'security_group_id': 'sg-0baac2c985b88fd23',
            'subnet_id': 'subnet-0d00b3a1ba2dd811b',
            'log_group': '/aws/ec2/selenium-scraper',
            'max_instances': 2  # Maximum number of concurrent instances
        }
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        logger.info("Received shutdown signal. Cleaning up...")
        self.running = False

    def get_running_instances(self):
        """Get currently running scraper instances"""
        response = self.ec2.describe_instances(
            Filters=[
                {'Name': 'instance-state-name', 'Values': ['pending', 'running']},
                {'Name': 'tag:Purpose', 'Values': ['dental-scraper']}
            ]
        )
        
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instances.append(instance)
        
        return instances

    def get_inactive_locations(self, country_code):
        """Get INACTIVE locations for a specific country"""
        response = self.dynamodb.query(
            TableName='dental_location_control',
            KeyConditionExpression='country_code = :cc',
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':cc': {'S': country_code},
                ':status': {'S': 'INACTIVE'}
            }
        )
        return response.get('Items', [])

    def get_location_stats(self, country_code):
        """Get statistics for locations in a country"""
        response = self.dynamodb.query(
            TableName='dental_location_control',
            KeyConditionExpression='country_code = :cc',
            ExpressionAttributeValues={
                ':cc': {'S': country_code}
            }
        )
        
        stats = {
            'total': 0,
            'inactive': 0,
            'in_progress': 0,
            'complete': 0,
            'stopped': 0
        }
        
        for item in response.get('Items', []):
            stats['total'] += 1
            status = item.get('status', {}).get('S', '').upper()
            if status == 'INACTIVE':
                stats['inactive'] += 1
            elif status == 'IN_PROGRESS':
                stats['in_progress'] += 1
            elif status == 'COMPLETE':
                stats['complete'] += 1
            elif status == 'STOPPED':
                stats['stopped'] += 1
        
        return stats

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

    def get_user_data(self, country_code, location_name):
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
apt-get install -y fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \\
    libcairo2 libcups2 libdbus-1-3 libdrm2 libgbm1 libgdk-pixbuf2.0-0 libgtk-3-0 libnspr4 \\
    libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \\
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
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/bin/config.json
systemctl start amazon-cloudwatch-agent

# Install Chrome
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing Chrome..."
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
dpkg -i google-chrome-stable_current_amd64.deb
apt-get -f install -y

# Install Python dependencies
pip3 install selenium==4.15.2 boto3 requests

# Create and run test script
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating test script..."
cat > /home/ubuntu/simple_test.py << 'EOF'
{test_code}
EOF

# Run the test
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running test..."
python3 /home/ubuntu/simple_test.py "{country_code}" "{location_name}"
'''
        except Exception as e:
            logger.error(f"Failed to generate user data: {str(e)}")
            raise

    def update_location_status(self, country_code, location_name, status, error_message=None):
        """Update location status in DynamoDB"""
        try:
            update_expr = "SET #status = :status, last_updated = :timestamp"
            expr_attrs = {
                ':status': {'S': status},
                ':timestamp': {'S': datetime.utcnow().isoformat()}
            }
            expr_names = {'#status': 'status'}
            
            if error_message:
                update_expr += ", error_message = :error"
                expr_attrs[':error'] = {'S': error_message}
            
            self.dynamodb.update_item(
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
            logger.error(f"Failed to update DynamoDB: {str(e)}")

    def ensure_log_group_exists(self):
        """Ensure CloudWatch log group exists"""
        try:
            self.logs.create_log_group(logGroupName=self.CONFIG['log_group'])
            logger.info(f"Created log group: {self.CONFIG['log_group']}")
        except self.logs.exceptions.ResourceAlreadyExistsException:
            logger.info(f"Log group already exists: {self.CONFIG['log_group']}")

    def launch_instance(self, country_code, location_name):
        """Launch EC2 instance with Chrome"""
        try:
            # First update status to IN_PROGRESS
            self.update_location_status(country_code, location_name, 'IN_PROGRESS')
            
            # Ensure log group exists
            self.ensure_log_group_exists()
            
            # Launch spot instance
            response = self.ec2.run_instances(
                ImageId='ami-003c3655bc8e97ae1',  # Ubuntu 22.04 LTS
                InstanceType='t3.medium',
                MinCount=1,
                MaxCount=1,
                SecurityGroupIds=[self.CONFIG['security_group_id']],
                SubnetId=self.CONFIG['subnet_id'],
                IamInstanceProfile={'Name': 'venue-scraper-profile'},
                InstanceMarketOptions={
                    'MarketType': 'spot',
                    'SpotOptions': {
                        'MaxPrice': '0.04',
                        'SpotInstanceType': 'one-time'
                    }
                },
                UserData=self.get_user_data(country_code, location_name),
                TagSpecifications=[{
                    'ResourceType': 'instance',
                    'Tags': [
                        {'Key': 'Name', 'Value': f'dental-scraper-{location_name}'},
                        {'Key': 'Purpose', 'Value': 'dental-scraper'},
                        {'Key': 'Location', 'Value': f'{country_code}#{location_name}'}
                    ]
                }]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            logger.info(f"Launched instance {instance_id}")
            return instance_id
            
        except Exception as e:
            # If launch fails, set status back to INACTIVE
            self.update_location_status(country_code, location_name, 'INACTIVE', str(e))
            logger.error(f"Failed to launch instance: {str(e)}")
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

    def terminate_self(self):
        """Terminate this controller instance"""
        try:
            # Get instance ID from metadata
            instance_id = requests.get(
                'http://169.254.169.254/latest/meta-data/instance-id',
                timeout=2
            ).text
            
            logger.info(f"All work complete. Terminating controller instance {instance_id}")
            self.ec2.terminate_instances(InstanceIds=[instance_id])
        except Exception as e:
            logger.error(f"Failed to terminate controller: {str(e)}", exc_info=True)
            sys.exit(1)

    def run_country(self, country_code):
        """Process all locations for a country"""
        try:
            logger.info(f"Starting dental practice scraper for country: {country_code}")
            logger.info("Testing AWS permissions...")
            
            # Test DynamoDB access
            try:
                stats = self.get_location_stats(country_code)
                logger.info(f"Successfully accessed DynamoDB. Found {stats['total']} locations")
            except Exception as e:
                logger.error(f"Failed to access DynamoDB: {str(e)}", exc_info=True)
                return
            
            # Test EC2 access
            try:
                instances = self.get_running_instances()
                logger.info(f"Successfully accessed EC2. Found {len(instances)} running instances")
            except Exception as e:
                logger.error(f"Failed to access EC2: {str(e)}", exc_info=True)
                return
            
            consecutive_complete_checks = 0
            while self.running:
                try:
                    # Get current stats
                    stats = self.get_location_stats(country_code)
                    logger.info(f"Country {country_code} progress: "
                            f"{stats['complete']}/{stats['total']} complete, "
                            f"{stats['in_progress']} in progress, "
                            f"{stats['stopped']} stopped")
                    
                    # Check if all locations are complete
                    if stats['complete'] == stats['total']:
                        # Wait for a few cycles to ensure everything is really done
                        consecutive_complete_checks += 1
                        if consecutive_complete_checks >= 3:  # Wait for 3 consecutive checks
                            logger.info(f"All locations in {country_code} have been processed!")
                            # Double check no instances are running
                            running_instances = self.get_running_instances()
                            if not running_instances:
                                self.terminate_self()
                                break
                            else:
                                logger.info(f"Waiting for {len(running_instances)} instances to terminate")
                                consecutive_complete_checks = 0  # Reset counter
                    else:
                        consecutive_complete_checks = 0  # Reset counter if not all complete
                    
                    # Get current running instances
                    running_instances = self.get_running_instances()
                    available_slots = self.CONFIG['max_instances'] - len(running_instances)
                    logger.info(f"Running instances: {len(running_instances)}, Available slots: {available_slots}")
                    
                    if available_slots > 0:
                        # Get INACTIVE locations
                        inactive_locations = self.get_inactive_locations(country_code)
                        if inactive_locations:
                            logger.info(f"Found {len(inactive_locations)} inactive locations")
                            
                            # Launch new instances up to the limit
                            for location in inactive_locations[:available_slots]:
                                location_name = location['location_name']['S']
                                try:
                                    instance_id = self.launch_instance(country_code, location_name)
                                    logger.info(f"Launched instance {instance_id} for {location_name}")
                                except Exception as e:
                                    logger.error(f"Failed to launch instance for {location_name}: {str(e)}", exc_info=True)
                    
                    # Wait before next check
                    time.sleep(30)
                    
                except Exception as e:
                    logger.error(f"Error in control loop: {str(e)}", exc_info=True)
                    if not self.running:
                        break
                    time.sleep(30)
            
        except Exception as e:
            logger.error(f"Fatal error in run_country: {str(e)}", exc_info=True)
        
        logger.info(f"Finished processing country: {country_code}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 task_runner_ec2.py <country_code>")
        print("Example: python3 task_runner_ec2.py UK")
        sys.exit(1)
    
    country_code = sys.argv[1].upper()
    runner = TaskRunner()
    runner.run_country(country_code)
