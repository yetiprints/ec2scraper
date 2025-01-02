import boto3
import time
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

class ControllerLauncher:
    def __init__(self):
        self.ec2 = boto3.client('ec2', region_name='eu-west-2')
        self.CONFIG = {
            'security_group_id': 'sg-0baac2c985b88fd23',
            'subnet_id': 'subnet-0d00b3a1ba2dd811b',
        }
    
    def get_controller_user_data(self, country_code):
        """Generate user data script for controller instance"""
        cloudwatch_config = '''{
    "agent": {
        "run_as_user": "root"
    },
    "logs": {
        "logs_collected": {
            "files": {
                "collect_list": [
                    {
                        "file_path": "/var/log/user-data.log",
                        "log_group_name": "/aws/ec2/dental-scraper-controller",
                        "log_stream_name": "{instance_id}",
                        "timezone": "UTC"
                    },
                    {
                        "file_path": "/opt/dental-scraper/controller.log",
                        "log_group_name": "/aws/ec2/dental-scraper-controller",
                        "log_stream_name": "{instance_id}-controller",
                        "timezone": "UTC"
                    }
                ]
            }
        }
    }
}'''
        
        return f'''#!/bin/bash
# Enable logging
exec 1> >(tee -a /var/log/user-data.log) 2>&1
set -x

# Wait for instance to fully initialize
sleep 10

# Install required packages
apt-get update
apt-get install -y python3-pip git awscli

# Set region
export AWS_DEFAULT_REGION=eu-west-2

# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
dpkg -i -E ./amazon-cloudwatch-agent.deb

# Configure CloudWatch agent
cat > /opt/aws/amazon-cloudwatch-agent/bin/config.json << 'EOF'
{cloudwatch_config}
EOF

# Start CloudWatch agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/bin/config.json
systemctl start amazon-cloudwatch-agent

# Install Python dependencies
pip3 install boto3 requests selenium

# Create working directory
mkdir -p /opt/dental-scraper
cd /opt/dental-scraper

# Debug AWS configuration
aws sts get-caller-identity || echo "Failed to get caller identity"
aws s3 ls || echo "Failed to list S3 buckets"

# Download our code files
echo "Downloading code files from S3..."
aws s3 ls s3://dental-scraper-code/ || echo "Failed to list dental-scraper-code bucket"
aws s3 cp s3://dental-scraper-code/task_runner_ec2.py . --debug || echo "Failed to download task_runner_ec2.py"
aws s3 cp s3://dental-scraper-code/simple_test.py . --debug || echo "Failed to download simple_test.py"

# Check if files exist
echo "Checking downloaded files..."
ls -la /opt/dental-scraper/
[ -f task_runner_ec2.py ] && echo "task_runner_ec2.py exists" || echo "task_runner_ec2.py not found"
[ -f simple_test.py ] && echo "simple_test.py exists" || echo "simple_test.py not found"

# Make files executable
chmod +x *.py 2>/dev/null || echo "Failed to make files executable"

# Run the controller (it will keep running until manually stopped)
cd /opt/dental-scraper
if [ -f task_runner_ec2.py ]; then
    python3 -u task_runner_ec2.py {country_code} 2>&1 | tee controller.log
else
    echo "ERROR: task_runner_ec2.py not found. Cannot start controller."
    exit 1
fi
'''

    def upload_code_to_s3(self):
        """Upload our code files to S3"""
        try:
            s3 = boto3.client('s3', region_name='eu-west-2')
            
            # Create bucket if it doesn't exist
            try:
                s3.create_bucket(
                    Bucket='dental-scraper-code',
                    CreateBucketConfiguration={'LocationConstraint': 'eu-west-2'}
                )
                logger.info("Created S3 bucket: dental-scraper-code")
            except s3.exceptions.BucketAlreadyExists:
                pass
            except s3.exceptions.BucketAlreadyOwnedByYou:
                pass
            
            # Upload files
            s3.upload_file('task_runner_ec2.py', 'dental-scraper-code', 'task_runner_ec2.py')
            s3.upload_file('simple_test.py', 'dental-scraper-code', 'simple_test.py')
            logger.info("Uploaded code files to S3")
            
        except Exception as e:
            logger.error(f"Failed to upload code to S3: {str(e)}")
            raise

    def launch_controller(self, country_code):
        """Launch t3.micro instance as controller"""
        try:
            # First upload our code to S3
            self.upload_code_to_s3()
            
            # Launch controller instance
            response = self.ec2.run_instances(
                ImageId='ami-003c3655bc8e97ae1',  # Ubuntu 22.04 LTS
                InstanceType='t3.micro',
                MinCount=1,
                MaxCount=1,
                SecurityGroupIds=[self.CONFIG['security_group_id']],
                SubnetId=self.CONFIG['subnet_id'],
                IamInstanceProfile={'Name': 'venue-scraper-profile'},
                UserData=self.get_controller_user_data(country_code),
                TagSpecifications=[{
                    'ResourceType': 'instance',
                    'Tags': [
                        {'Key': 'Name', 'Value': f'dental-scraper-controller-{country_code}'},
                        {'Key': 'Purpose', 'Value': 'dental-scraper-controller'}
                    ]
                }]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            logger.info(f"Launched controller instance {instance_id}")
            
            # Wait for instance to be running
            logger.info("Waiting for controller to start...")
            waiter = self.ec2.get_waiter('instance_running')
            waiter.wait(InstanceIds=[instance_id])
            
            # Get instance details
            instance = self.ec2.describe_instances(
                InstanceIds=[instance_id]
            )['Reservations'][0]['Instances'][0]
            
            public_ip = instance.get('PublicIpAddress')
            logger.info(f"\nController is running!")
            logger.info(f"Instance ID: {instance_id}")
            logger.info(f"Public IP: {public_ip}")
            logger.info(f"\nTo check status:")
            logger.info(f"1. View in AWS Console: https://eu-west-2.console.aws.amazon.com/ec2/home?region=eu-west-2#InstanceDetails:instanceId={instance_id}")
            logger.info(f"2. SSH to instance: ssh ubuntu@{public_ip}")
            logger.info(f"3. View logs: tail -f /var/log/user-data.log")
            logger.info(f"\nTo stop the controller:")
            logger.info(f"aws ec2 terminate-instances --instance-ids {instance_id}")
            
            return instance_id
            
        except Exception as e:
            logger.error(f"Failed to launch controller: {str(e)}")
            raise

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 launch_controller.py <country_code>")
        print("Example: python3 launch_controller.py UK")
        sys.exit(1)
    
    country_code = sys.argv[1].upper()
    launcher = ControllerLauncher()
    launcher.launch_controller(country_code)
