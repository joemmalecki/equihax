from typing import Optional
from .db import DatabaseConnection
from .tenants import Tenant


class TenantClient:
    """
    Scoped client for a single tenant. All queries automatically target
    the tenant's schema — no need to specify it on each call.

    Obtained via:
        acme = client.tenant("acme")

    Supports built-in operations and ad-hoc queries for custom use cases:
        acme.get_messages()
        acme.save_message("Hello!")
        acme.query("SELECT * FROM orders WHERE status = %s", ("pending",))
    """

    def __init__(self, tenant: Tenant, db: DatabaseConnection):
        self._tenant = tenant
        self._db = db

    @property
    def info(self) -> Tenant:
        """Returns the tenant metadata (subdomain, display_name, tier, status, etc.)."""
        return self._tenant

    # -------------------------------------------------------------------------
    # Built-in application operations
    # -------------------------------------------------------------------------

    def get_messages(self) -> list[dict]:
        """Fetch all messages for this tenant, newest first."""
        return self._db.query(
            "SELECT * FROM messages ORDER BY created_at DESC",
            database=self._tenant.schema_name,
        )

    def save_message(self, message: str):
        """Insert a new message into this tenant's schema."""
        self._db.execute(
            "INSERT INTO messages (message) VALUES (%s)",
            (message,),
            database=self._tenant.schema_name,
        )

    # -------------------------------------------------------------------------
    # Ad-hoc access for custom queries and joins
    # -------------------------------------------------------------------------

    def query(self, sql: str, args: tuple = None) -> list[dict]:
        """Run an arbitrary SELECT against this tenant's schema."""
        return self._db.query(sql, args, database=self._tenant.schema_name)

    def query_one(self, sql: str, args: tuple = None) -> Optional[dict]:
        """Run an arbitrary SELECT and return a single row."""
        return self._db.query_one(sql, args, database=self._tenant.schema_name)

    def execute(self, sql: str, args: tuple = None) -> int:
        """Run an arbitrary write statement against this tenant's schema."""
        return self._db.execute(sql, args, database=self._tenant.schema_name)
