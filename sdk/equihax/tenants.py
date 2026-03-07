import re
import os
from dataclasses import dataclass
from typing import Optional
from .db import DatabaseConnection

RESERVED_SUBDOMAINS = {
    "www", "mail", "admin", "api", "dev", "staging",
    "mysql", "root", "tenants", "equihax"
}


@dataclass
class Tenant:
    id: int
    schema_name: str
    subdomain: str
    display_name: str
    tier: str
    status: str
    created_at: str
    updated_at: str


class TenantManager:
    """
    Manages tenant lifecycle — provisioning, suspension, deprovisioning.
    All operations run against the tenants_registry database on the
    target environment's RDS instance.
    """

    def __init__(self, db: DatabaseConnection):
        self.db = db

    def list_tenants(self, status: str = "active") -> list[Tenant]:
        rows = self.db.query(
            "SELECT * FROM tenants WHERE status = %s ORDER BY created_at DESC",
            (status,)
        )
        return [self._to_tenant(row) for row in rows]

    def get_tenant(self, subdomain: str) -> Optional[Tenant]:
        row = self.db.query_one(
            "SELECT * FROM tenants WHERE subdomain = %s",
            (subdomain,)
        )
        return self._to_tenant(row) if row else None

    def provision_tenant(self, subdomain: str, display_name: str, tier: str = "free") -> Tenant:
        """
        Full tenant provisioning:
        1. Validate subdomain
        2. Create schema
        3. Run migrations
        4. Register in tenants_registry
        """
        self._validate_subdomain(subdomain)

        if self.get_tenant(subdomain):
            raise ValueError(f"Tenant '{subdomain}' already exists")

        schema_name = self._subdomain_to_schema(subdomain)

        # 1. Create schema
        self.db.execute(f"CREATE DATABASE `{schema_name}`")
        print(f"[INFO] Created schema '{schema_name}'")

        # 2. Run migrations (Flyway or SQL files)
        self._run_migrations(schema_name)

        # 3. Register tenant
        self.db.execute(
            """
            INSERT INTO tenants (schema_name, subdomain, display_name, tier, status)
            VALUES (%s, %s, %s, %s, 'active')
            """,
            (schema_name, subdomain, display_name, tier)
        )

        print(f"[INFO] Tenant '{subdomain}' provisioned at {subdomain}.equihax.net")
        return self.get_tenant(subdomain)

    def suspend_tenant(self, subdomain: str):
        """Suspends tenant — blocks access without deleting data."""
        self._require_tenant(subdomain)
        self.db.execute(
            "UPDATE tenants SET status = 'suspended' WHERE subdomain = %s",
            (subdomain,)
        )
        print(f"[INFO] Tenant '{subdomain}' suspended")

    def reactivate_tenant(self, subdomain: str):
        self._require_tenant(subdomain)
        self.db.execute(
            "UPDATE tenants SET status = 'active' WHERE subdomain = %s",
            (subdomain,)
        )
        print(f"[INFO] Tenant '{subdomain}' reactivated")

    def deprovision_tenant(self, subdomain: str):
        """
        Permanently removes tenant. Drops schema and deletes registry entry.
        This is irreversible — call suspend_tenant first if unsure.
        """
        tenant = self._require_tenant(subdomain)
        schema_name = tenant.schema_name

        # Remove registry entry first
        self.db.execute(
            "DELETE FROM tenants WHERE subdomain = %s",
            (subdomain,)
        )

        # Drop schema
        self.db.execute(f"DROP DATABASE `{schema_name}`")

        print(f"[INFO] Tenant '{subdomain}' deprovisioned and schema dropped")

    def get_count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) as count FROM tenants WHERE status = 'active'")
        return row["count"] if row else 0

    def _run_migrations(self, schema_name: str):
        """
        Runs tenant_setup.sql against the newly created tenant schema
        to set up tables and seed initial data.
        """
        migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
        sql_path = os.path.join(migrations_dir, "tenant_setup.sql")

        with open(sql_path, "r") as f:
            sql = f.read()

        statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
        for statement in statements:
            self.db.execute(statement, database=schema_name)

        print(f"[INFO] Migrations applied to '{schema_name}'")

    def _validate_subdomain(self, subdomain: str):
        if subdomain in RESERVED_SUBDOMAINS:
            raise ValueError(f"'{subdomain}' is a reserved name")
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', subdomain):
            raise ValueError(
                f"Invalid subdomain '{subdomain}'. "
                "Must be lowercase alphanumeric with hyphens, cannot start or end with a hyphen."
            )

    def _subdomain_to_schema(self, subdomain: str) -> str:
        return subdomain.replace("-", "_")

    def _require_tenant(self, subdomain: str) -> Tenant:
        tenant = self.get_tenant(subdomain)
        if not tenant:
            raise ValueError(f"Tenant '{subdomain}' not found")
        return tenant

    def _to_tenant(self, row: dict) -> Tenant:
        return Tenant(
            id=row["id"],
            schema_name=row["schema_name"],
            subdomain=row["subdomain"],
            display_name=row["display_name"],
            tier=row["tier"],
            status=row["status"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
