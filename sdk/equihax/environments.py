import subprocess
import boto3
import json
from dataclasses import dataclass
from typing import Optional
import socket
from .db import DatabaseConnection, _BastionTunnel

TENANT_CAPACITY_THRESHOLD = 100


@dataclass
class Environment:
    environment_id: str
    db_host: str
    secret_name: str
    region: str
    tenant_count: int
    status: str


class EnvironmentManager:
    """
    Manages AWS environments (CDK stacks).
    Each environment is a full nginx + Apache + RDS deployment
    capable of serving up to TENANT_CAPACITY_THRESHOLD tenants.
    """

    # Central registry of all environments — stored in a dedicated
    # DynamoDB table so the SDK can discover them without hardcoding.
    ENVIRONMENTS_TABLE = "equihax_environments"

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(self.ENVIRONMENTS_TABLE)
        self._ensure_registry_table()

    def _ensure_registry_table(self):
        """Creates the equihax_environments DynamoDB table if it doesn't exist."""
        client = boto3.client("dynamodb", region_name=self.region)
        try:
            client.describe_table(TableName=self.ENVIRONMENTS_TABLE)
        except client.exceptions.ResourceNotFoundException:
            print(f"[INFO] Creating DynamoDB table '{self.ENVIRONMENTS_TABLE}'...")
            self._dynamodb.create_table(
                TableName=self.ENVIRONMENTS_TABLE,
                KeySchema=[{"AttributeName": "environment_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "environment_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            self._table.wait_until_exists()
            print(f"[INFO] DynamoDB table '{self.ENVIRONMENTS_TABLE}' ready.")

    def list_environments(self) -> list[Environment]:
        response = self._table.scan()
        return [self._to_environment(item) for item in response["Items"]]

    def get_environment(self, environment_id: str) -> Optional[Environment]:
        response = self._table.get_item(Key={"environment_id": environment_id})
        item = response.get("Item")
        return self._to_environment(item) if item else None

    def get_active_environment(self) -> Optional[Environment]:
        """
        Returns the environment that should receive new tenants.
        Prints a warning if the environment is approaching capacity.
        Returns None if all environments are full.
        """
        envs = self.list_environments()
        active = [e for e in envs if e.status == "active"]

        for env in active:
            if env.tenant_count < TENANT_CAPACITY_THRESHOLD:
                remaining = TENANT_CAPACITY_THRESHOLD - env.tenant_count
                if remaining <= 10:
                    print(
                        f"[WARN] Environment '{env.environment_id}' is approaching capacity "
                        f"({env.tenant_count}/{TENANT_CAPACITY_THRESHOLD} tenants). "
                        f"Call deploy_environment() to provision a new one."
                    )
                return env

        return None

    def increment_tenant_count(self, environment_id: str):
        self._table.update_item(
            Key={"environment_id": environment_id},
            UpdateExpression="SET tenant_count = tenant_count + :val",
            ExpressionAttributeValues={":val": 1}
        )

    def decrement_tenant_count(self, environment_id: str):
        self._table.update_item(
            Key={"environment_id": environment_id},
            UpdateExpression="SET tenant_count = tenant_count - :val",
            ConditionExpression="tenant_count > :zero",
            ExpressionAttributeValues={":val": 1, ":zero": 0}
        )

    def deploy_environment(self, environment_id: str, account: str) -> Environment:
        """
        Manually triggered after auto-flag warning.
        Runs CDK deploy for a new environment and registers it.
        """
        if self.get_environment(environment_id):
            raise ValueError(
                f"Environment '{environment_id}' already exists. "
                "Use a new environment_id."
            )

        print(f"[INFO] Deploying new environment '{environment_id}'...")

        existing = self.list_environments()
        deploy_dns = "true" if not existing else "false"

        result = subprocess.run(
            [
                "cdk", "deploy", "--all",
                "--context", f"account={account}",
                "--context", f"environment_id={environment_id}",
                "--context", f"region={self.region}",
                "--context", f"deploy_dns={deploy_dns}",
                "--outputs-file", "cdk.out/outputs.json",
                "--require-approval", "never"
            ],
            cwd="../infra",
            capture_output=False,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"CDK deploy failed:\n{result.stderr}")

        # Parse CDK outputs to get the new RDS endpoint
        outputs = self._parse_cdk_outputs(environment_id)

        env = Environment(
            environment_id=environment_id,
            db_host=outputs["db_endpoint"],
            secret_name=f"equihax/{environment_id}/db/credentials",
            region=self.region,
            tenant_count=0,
            status="active"
        )

        # Bootstrap tenants_registry via bastion tunnel (RDS is in private subnet)
        tunnel = None
        try:
            try:
                sock = socket.create_connection((env.db_host, 3306), timeout=2.0)
                sock.close()
                db_host = env.db_host
                db_port = 3306
            except OSError:
                tunnel = _BastionTunnel(
                    environment_id=environment_id,
                    db_host=env.db_host,
                    region=self.region,
                )
                tunnel.start()
                db_host = "127.0.0.1"
                db_port = _BastionTunnel.LOCAL_PORT

            db = DatabaseConnection(
                secret_name=env.secret_name,
                host=db_host,
                port=db_port,
                region=self.region,
            )
            db.bootstrap_registry()
        finally:
            if tunnel:
                tunnel.stop()

        # Only register in DynamoDB after bootstrap succeeds
        self._table.put_item(Item=self._from_environment(env))

        print(f"[INFO] Environment '{environment_id}' deployed and registered.")
        return env

    def _parse_cdk_outputs(self, environment_id: str) -> dict:
        """Read CDK output JSON to extract stack outputs like RDS endpoint."""
        try:
            with open("../infra/cdk.out/outputs.json") as f:
                outputs = json.load(f)
            stack_key = f"EquihaxDatabase-{environment_id}"
            return {
                "db_endpoint": outputs[stack_key]["DbEndpoint"]
            }
        except (FileNotFoundError, KeyError) as e:
            raise RuntimeError(f"Could not parse CDK outputs: {e}")

    def _to_environment(self, item: dict) -> Environment:
        return Environment(
            environment_id=item["environment_id"],
            db_host=item["db_host"],
            secret_name=item["secret_name"],
            region=item.get("region", self.region),
            tenant_count=int(item.get("tenant_count", 0)),
            status=item.get("status", "active")
        )

    def _from_environment(self, env: Environment) -> dict:
        return {
            "environment_id": env.environment_id,
            "db_host": env.db_host,
            "secret_name": env.secret_name,
            "region": env.region,
            "tenant_count": env.tenant_count,
            "status": env.status
        }
