import os
import pymysql
import boto3
import json
from typing import Optional


class DatabaseConnection:
    """
    Low-level database connection manager.
    Fetches credentials from AWS Secrets Manager and connects to RDS.
    """

    def __init__(self, secret_name: str, host: str, region: str = "us-east-1"):
        self.host = host
        self.region = region
        self._credentials = self._fetch_credentials(secret_name)

    def _fetch_credentials(self, secret_name: str) -> dict:
        client = boto3.client("secretsmanager", region_name=self.region)
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])

    def get_connection(self, database: Optional[str] = "tenants_registry") -> pymysql.Connection:
        kwargs = dict(
            host=self.host,
            user=self._credentials["username"],
            password=self._credentials["password"],
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        if database is not None:
            kwargs["database"] = database
        return pymysql.connect(**kwargs)

    def bootstrap_registry(self):
        """
        Creates the tenants_registry database and tenants table on a fresh RDS instance.
        Connects without selecting a database so it can run CREATE DATABASE safely.
        """
        migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
        sql_path = os.path.join(migrations_dir, "registry_setup.sql")

        with open(sql_path, "r") as f:
            sql = f.read()

        statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
        conn = self.get_connection(database=None)
        try:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
            conn.commit()
        finally:
            conn.close()

        print("[INFO] tenants_registry bootstrapped")

    def execute(self, sql: str, args: Optional[tuple] = None, database: str = "tenants_registry"):
        """Execute a single statement and return affected rows."""
        conn = self.get_connection(database)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, args)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def query(self, sql: str, args: Optional[tuple] = None, database: str = "tenants_registry") -> list:
        """Execute a SELECT and return all rows."""
        conn = self.get_connection(database)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, args)
                return cursor.fetchall()
        finally:
            conn.close()

    def query_one(self, sql: str, args: Optional[tuple] = None, database: str = "tenants_registry") -> Optional[dict]:
        """Execute a SELECT and return a single row."""
        rows = self.query(sql, args, database)
        return rows[0] if rows else None
