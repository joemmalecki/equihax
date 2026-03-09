import json
import os
import subprocess
import time
from typing import Optional

import boto3
import pymysql


class _BastionTunnel:
    """
    Internal — starts the SSM bastion and opens a port-forwarding tunnel to RDS.
    Managed exclusively by EquihaxClient; not part of the public API.
    """

    LOCAL_PORT = 13306

    def __init__(self, environment_id: str, db_host: str, region: str = "us-east-1"):
        self.environment_id = environment_id
        self.db_host = db_host
        self.region = region
        self._instance_id: Optional[str] = None
        self._tunnel_proc: Optional[subprocess.Popen] = None

    def start(self):
        self._instance_id = self._get_instance_id()
        self._start_instance()
        self._start_tunnel()

    def stop(self):
        if self._tunnel_proc:
            self._tunnel_proc.terminate()
            self._tunnel_proc = None
            print("[INFO] Tunnel closed. Bastion will shut itself down.")

    def _get_instance_id(self) -> str:
        client = boto3.client("ssm", region_name=self.region)
        param = client.get_parameter(
            Name=f"/equihax/{self.environment_id}/bastion/instance_id"
        )
        return param["Parameter"]["Value"]

    def _start_instance(self):
        ec2 = boto3.client("ec2", region_name=self.region)
        response = ec2.describe_instances(InstanceIds=[self._instance_id])
        state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
        if state == "running":
            print(f"[INFO] Bastion {self._instance_id} already running.")
            return
        ec2.start_instances(InstanceIds=[self._instance_id])
        print(f"[INFO] Starting bastion {self._instance_id}...")
        waiter = ec2.get_waiter("instance_running")
        waiter.wait(InstanceIds=[self._instance_id])
        time.sleep(8)
        print("[INFO] Bastion ready.")

    def _start_tunnel(self):
        self._tunnel_proc = subprocess.Popen(
            [
                "aws", "ssm", "start-session",
                "--target", self._instance_id,
                "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
                "--parameters", json.dumps({
                    "host": [self.db_host],
                    "portNumber": ["3306"],
                    "localPortNumber": [str(self.LOCAL_PORT)],
                }),
                "--region", self.region,
            ]
        )
        time.sleep(3)
        print(f"[INFO] SSM tunnel open on localhost:{self.LOCAL_PORT}")


class DatabaseConnection:
    """
    Holds a single persistent connection to RDS for the lifetime of the session.
    Reconnects automatically if the connection drops.
    Switches database context via USE when operations target a different schema.
    """

    def __init__(self, secret_name: str, host: str, region: str = "us-east-1",
                 port: int = 3306):
        self.host = host
        self.port = port
        self.region = region
        self._credentials = self._fetch_credentials(secret_name)
        self._conn: Optional[pymysql.Connection] = None
        self._current_database: Optional[str] = None

    def _fetch_credentials(self, secret_name: str) -> dict:
        client = boto3.client("secretsmanager", region_name=self.region)
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])

    def _connection(self) -> pymysql.Connection:
        """Returns the persistent connection, reconnecting if dropped."""
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self._credentials["username"],
                password=self._credentials["password"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
            self._current_database = None
        return self._conn

    def _use_database(self, database: Optional[str]):
        """Switch database context if different from current."""
        if database == self._current_database:
            return
        conn = self._connection()
        if database is not None:
            with conn.cursor() as cursor:
                cursor.execute(f"USE `{database}`")
        self._current_database = database

    def close(self):
        """Explicitly close the connection. Called by EquihaxClient on exit."""
        if self._conn and self._conn.open:
            self._conn.close()
        self._conn = None
        self._current_database = None

    def bootstrap_registry(self):
        """
        Creates the tenants_registry database and tenants table on a fresh RDS instance.
        Runs without a database selected so CREATE DATABASE executes safely.
        """
        migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
        sql_path = os.path.join(migrations_dir, "registry_setup.sql")
        with open(sql_path, "r") as f:
            sql = f.read()
        self.execute_script(sql, database=None)
        print("[INFO] tenants_registry bootstrapped")

    def execute_script(self, sql: str, database: Optional[str] = None):
        """
        Run multiple SQL statements in a single connection.
        Use for migrations and setup scripts where statements depend on each other.
        """
        self._use_database(database)
        conn = self._connection()
        stripped = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
        statements = [s.strip() for s in stripped.split(";") if s.strip()]
        with conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        conn.commit()

    def execute(self, sql: str, args: Optional[tuple] = None, database: str = "tenants_registry") -> int:
        """Execute a single parameterized statement and return affected rows."""
        self._use_database(database)
        conn = self._connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, args)
            rowcount = cursor.rowcount
        conn.commit()
        return rowcount

    def query(self, sql: str, args: Optional[tuple] = None, database: str = "tenants_registry") -> list:
        """Execute a SELECT and return all rows."""
        self._use_database(database)
        conn = self._connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()

    def query_one(self, sql: str, args: Optional[tuple] = None, database: str = "tenants_registry") -> Optional[dict]:
        """Execute a SELECT and return a single row."""
        rows = self.query(sql, args, database)
        return rows[0] if rows else None
