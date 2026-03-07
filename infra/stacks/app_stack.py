from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_secretsmanager as secretsmanager,
    aws_logs as logs,
)
from constructs import Construct


class AppStack(Stack):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.Vpc,
                 db_secret: secretsmanager.ISecret,
                 db_endpoint: str,
                 **kwargs):
        super().__init__(scope, id, **kwargs)

        # ECS Cluster
        cluster = ecs.Cluster(
            self, "EquihaxCluster",
            vpc=vpc,
            cluster_name="equihax"
        )

        # Lookup hosted zone for equihax.net
        hosted_zone = route53.HostedZone.from_lookup(
            self, "EquihaxZone",
            domain_name="equihax.net"
        )

        # Wildcard SSL cert for *.equihax.net
        certificate = acm.Certificate(
            self, "WildcardCert",
            domain_name="*.equihax.net",
            subject_alternative_names=["equihax.net"],
            validation=acm.CertificateValidation.from_dns(hosted_zone)
        )

        # ALB Security Group
        alb_sg = ec2.SecurityGroup(
            self, "AlbSg",
            vpc=vpc,
            description="ALB security group",
            allow_all_outbound=True
        )
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80))
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443))

        # ECS Security Group
        ecs_sg = ec2.SecurityGroup(
            self, "EcsSg",
            vpc=vpc,
            description="ECS Fargate security group",
            allow_all_outbound=True
        )
        ecs_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(80))

        # Application Load Balancer
        self.alb = elbv2.ApplicationLoadBalancer(
            self, "EquihaxAlb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            )
        )

        # Redirect HTTP to HTTPS
        self.alb.add_listener(
            "HttpListener",
            port=80,
            default_action=elbv2.ListenerAction.redirect(
                protocol="HTTPS",
                port="443",
                permanent=True
            )
        )

        # HTTPS listener
        https_listener = self.alb.add_listener(
            "HttpsListener",
            port=443,
            certificates=[certificate],
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404,
                content_type="text/plain",
                message_body="No tenant specified"
            )
        )

        # Fargate task definition - nginx + apache as sidecar
        task_def = ecs.FargateTaskDefinition(
            self, "EquihaxTask",
            cpu=256,
            memory_limit_mib=512,
        )

        # Grant task access to DB secret
        db_secret.grant_read(task_def.task_role)

        # nginx container (public facing)
        nginx_container = task_def.add_container(
            "nginx",
            image=ecs.ContainerImage.from_asset("../app/nginx"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="nginx",
                log_group=logs.LogGroup(self, "NginxLogs")
            ),
            environment={
                "APACHE_HOST": "localhost",
                "APACHE_PORT": "8080"
            }
        )
        nginx_container.add_port_mappings(
            ecs.PortMapping(container_port=80)
        )

        # Apache + PHP container (sidecar)
        apache_container = task_def.add_container(
            "apache",
            image=ecs.ContainerImage.from_asset("../app/apache"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="apache",
                log_group=logs.LogGroup(self, "ApacheLogs")
            ),
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db_secret, "password"),
                "DB_USERNAME": ecs.Secret.from_secrets_manager(db_secret, "username"),
            },
            environment={
                "DB_HOST": db_endpoint,
                "DB_NAME": "tenants_registry"
            }
        )
        apache_container.add_port_mappings(
            ecs.PortMapping(container_port=8080)
        )

        # ECS Fargate Service
        service = ecs.FargateService(
            self, "EquihaxService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            security_groups=[ecs_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            assign_public_ip=False
        )

        # Target group pointing to nginx port 80
        target_group = elbv2.ApplicationTargetGroup(
            self, "EquihaxTg",
            vpc=vpc,
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/",
                healthy_http_codes="200,301,302,404"
            )
        )

        # Route *.equihax.net to ECS service
        https_listener.add_action(
            "TenantRule",
            priority=1,
            conditions=[
                elbv2.ListenerCondition.host_headers(["*.equihax.net"])
            ],
            action=elbv2.ListenerAction.forward([target_group])
        )

        # Auto scaling
        scaling = service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=10
        )
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(60)
        )
