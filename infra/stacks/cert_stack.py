from aws_cdk import (
    Stack,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_ssm as ssm,
)
from constructs import Construct


class CertStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        hosted_zone = route53.HostedZone.from_lookup(
            self, "EquihaxZone",
            domain_name="equihax.net"
        )

        self.certificate = acm.Certificate(
            self, "WildcardCert",
            domain_name="*.equihax.net",
            subject_alternative_names=["equihax.net"],
            validation=acm.CertificateValidation.from_dns(hosted_zone)
        )

        ssm.StringParameter(
            self, "CertArnParam",
            parameter_name="/equihax/certificate_arn",
            string_value=self.certificate.certificate_arn
        )
