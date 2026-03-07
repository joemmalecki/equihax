from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
)
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
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
