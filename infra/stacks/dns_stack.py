from aws_cdk import (
    Stack,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct


class DnsStack(Stack):
    def __init__(self, scope: Construct, id: str,
                 alb: elbv2.ApplicationLoadBalancer,
                 **kwargs):
        super().__init__(scope, id, **kwargs)

        hosted_zone = route53.HostedZone.from_lookup(
            self, "EquihaxZone",
            domain_name="equihax.net"
        )

        # Wildcard A record — *.equihax.net → ALB
        route53.ARecord(
            self, "WildcardRecord",
            zone=hosted_zone,
            record_name="*",
            target=route53.RecordTarget.from_alias(
                targets.LoadBalancerTarget(alb)
            )
        )

        # Apex record — equihax.net → ALB
        route53.ARecord(
            self, "ApexRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.LoadBalancerTarget(alb)
            )
        )
