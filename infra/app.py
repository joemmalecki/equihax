#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.database_stack import DatabaseStack
from stacks.app_stack import AppStack
from stacks.cert_stack import CertStack
from stacks.dns_stack import DnsStack

app = cdk.App()

environment_id = app.node.try_get_context("environment_id") or "prod-1"
deploy_dns = app.node.try_get_context("deploy_dns") != "false"

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1"
)

network = NetworkStack(app, f"EquihaxNetwork-{environment_id}", env=env)

database = DatabaseStack(app, f"EquihaxDatabase-{environment_id}",
    vpc=network.vpc,
    rds_sg=network.rds_sg,
    environment_id=environment_id,
    env=env
)

certificate = None
if deploy_dns:
    cert_stack = CertStack(app, "EquihaxCert", env=env)
    certificate = cert_stack.certificate

app_stack = AppStack(app, f"EquihaxApp-{environment_id}",
    vpc=network.vpc,
    db_secret=database.db_secret,
    db_endpoint=database.db_endpoint,
    environment_id=environment_id,
    alb_sg=network.alb_sg,
    ecs_sg=network.ecs_sg,
    certificate=certificate,
    env=env
)

if deploy_dns:
    DnsStack(app, "EquihaxDns",
        alb=app_stack.alb,
        env=env
    )

app.synth()
