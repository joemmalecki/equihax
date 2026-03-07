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

    def get_connection(self, database: str = "tenants_registry") -> pymysql.Connection:
        return pymysql.connect(
            host=self.host,
            user=self._credentials["username"],
            password=self._credentials["password"],
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False
        )

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
