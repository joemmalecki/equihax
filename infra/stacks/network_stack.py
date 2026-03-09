from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_ssm as ssm,
)
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, environment_id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # VPC with public subnets for ALB and private subnets for ECS + RDS
        self.vpc = ec2.Vpc(
            self, "EquihaxVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24
                ),
            ]
        )

        # Security group for the Application Load Balancer
        self.alb_sg = ec2.SecurityGroup(
            self, "AlbSg",
            vpc=self.vpc,
            description="Allow HTTP and HTTPS from internet",
            allow_all_outbound=True
        )
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80))
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443))

        # Security group for ECS Fargate tasks
        self.ecs_sg = ec2.SecurityGroup(
            self, "EcsSg",
            vpc=self.vpc,
            description="Allow traffic from ALB only",
            allow_all_outbound=True
        )
        self.ecs_sg.add_ingress_rule(self.alb_sg, ec2.Port.tcp(80))

        # Security group for RDS - only accept from ECS
        self.rds_sg = ec2.SecurityGroup(
            self, "RdsSg",
            vpc=self.vpc,
            description="Allow MySQL from ECS only",
            allow_all_outbound=False
        )
        self.rds_sg.add_ingress_rule(self.ecs_sg, ec2.Port.tcp(3306))

        # Security group for bastion - no inbound, SSM is outbound only
        self.bastion_sg = ec2.SecurityGroup(
            self, "BastionSg",
            vpc=self.vpc,
            description="Bastion host - SSM only, no open ports",
            allow_all_outbound=True
        )

        # IAM role for bastion - SSM managed instance core only
        bastion_role = iam.Role(
            self, "BastionRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ]
        )

        # User data: set up session monitor service on first boot
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "cat > /usr/local/bin/session-monitor.sh << 'SCRIPT'",
            "#!/bin/bash",
            "TIMEOUT=300",
            "elapsed=0",
            "while ! pgrep -f 'ssm-session-worker' > /dev/null 2>&1; do",
            "    sleep 5",
            "    elapsed=$((elapsed + 5))",
            "    if [ $elapsed -ge $TIMEOUT ]; then",
            "        /sbin/shutdown -h now",
            "        exit",
            "    fi",
            "done",
            "while pgrep -f 'ssm-session-worker' > /dev/null 2>&1; do",
            "    sleep 5",
            "done",
            "/sbin/shutdown -h now",
            "SCRIPT",
            "chmod +x /usr/local/bin/session-monitor.sh",
            "cat > /etc/systemd/system/session-monitor.service << 'SERVICE'",
            "[Unit]",
            "Description=Auto-shutdown when SSM session ends",
            "After=amazon-ssm-agent.service",
            "[Service]",
            "Type=simple",
            "ExecStart=/usr/local/bin/session-monitor.sh",
            "[Install]",
            "WantedBy=multi-user.target",
            "SERVICE",
            "systemctl daemon-reload",
            "systemctl enable session-monitor",
            "systemctl start session-monitor",
        )

        # Bastion EC2 - t3.nano, private subnet, no public IP
        bastion = ec2.Instance(
            self, "Bastion",
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.NANO),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=self.bastion_sg,
            role=bastion_role,
            user_data=user_data,
        )

        # Store instance ID so SDK can look it up without hardcoding
        ssm.StringParameter(
            self, "BastionInstanceId",
            parameter_name=f"/equihax/{environment_id}/bastion/instance_id",
            string_value=bastion.instance_id,
        )
