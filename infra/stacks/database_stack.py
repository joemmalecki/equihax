from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class DatabaseStack(Stack):
    def __init__(self, scope: Construct, id: str, vpc: ec2.Vpc, rds_sg: ec2.SecurityGroup,
                 bastion_sg: ec2.SecurityGroup, environment_id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # RDS MariaDB instance
        self.db_instance = rds.DatabaseInstance(
            self, "EquihaxDb",
            engine=rds.DatabaseInstanceEngine.maria_db(
                version=rds.MariaDbEngineVersion.VER_10_6
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3,
                ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[rds_sg],
            database_name="tenants_registry",       # first DB created on the instance
            multi_az=False,                         # set True for production HA
            allocated_storage=20,
            max_allocated_storage=100,              # autoscaling storage up to 100GB
            deletion_protection=True,               # prevents accidental deletion
            removal_policy=RemovalPolicy.SNAPSHOT,  # snapshot on stack deletion
            backup_retention=Duration.days(7),
            credentials=rds.Credentials.from_generated_secret(
                "httpdclient",
                secret_name=f"equihax/{environment_id}/db/credentials"
            )
        )

        # Allow bastion to reach RDS for admin/SDK operations
        rds_sg.add_ingress_rule(bastion_sg, ec2.Port.tcp(3306))

        # Expose secret and endpoint for use in app stack
        self.db_secret = self.db_instance.secret
        self.db_endpoint = self.db_instance.db_instance_endpoint_address

        CfnOutput(self, "DbEndpoint", value=self.db_endpoint)
