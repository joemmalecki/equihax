#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.database_stack import DatabaseStack
from stacks.app_stack import AppStack
from stacks.dns_stack import DnsStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1"
)

network = NetworkStack(app, "EquihaxNetwork", env=env)

database = DatabaseStack(app, "EquihaxDatabase",
    vpc=network.vpc,
    env=env
)

app_stack = AppStack(app, "EquihaxApp",
    vpc=network.vpc,
    db_secret=database.db_secret,
    db_endpoint=database.db_endpoint,
    env=env
)

dns = DnsStack(app, "EquihaxDns",
    alb=app_stack.alb,
    env=env
)

app.synth()
