import socket
from typing import Optional

from .db import DatabaseConnection, _BastionTunnel
from .tenant_client import TenantClient
from .tenants import TenantManager, Tenant
from .environments import EnvironmentManager, Environment, TENANT_CAPACITY_THRESHOLD


def _can_reach_db(host: str, port: int = 3306, timeout: float = 2.0) -> bool:
    """Returns True if RDS is directly reachable (i.e. running inside the VPC)."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


class EquihaxClient:
    """
    Main entry point for the Equihax SDK. Must be used as a context manager.

    Automatically detects whether it's running inside or outside the VPC:
    - Inside VPC: connects to RDS directly
    - Outside VPC: starts the SSM bastion tunnel, closes it on exit

    Usage:
        with EquihaxClient(environment_id="prod-1") as client:
            # Platform operations
            client.provision_tenant("acme", "Acme Corp")
            client.list_tenants()
            client.get_capacity()

            # Tenant-scoped operations
            acme = client.tenant("acme")
            acme.get_messages()
            acme.save_message("Hello!")
            acme.query("SELECT * FROM orders WHERE status = %s", ("pending",))
    """

    def __init__(self, environment_id: str, region: str = "us-east-1"):
        self._environment_id = environment_id
        self._region = region
        self._env_manager = EnvironmentManager(region=region)
        self._environment: Optional[Environment] = None
        self._db: Optional[DatabaseConnection] = None
        self._tunnel: Optional[_BastionTunnel] = None
        self._tenant_manager: Optional[TenantManager] = None

    def __enter__(self):
        env = self._env_manager.get_environment(self._environment_id)
        if not env:
            raise ValueError(
                f"Environment '{self._environment_id}' not found. "
                "Run deploy_environment() to create it first."
            )
        self._environment = env

        if _can_reach_db(env.db_host):
            print("[INFO] Connecting to RDS directly.")
            self._db = DatabaseConnection(
                secret_name=env.secret_name,
                host=env.db_host,
                region=self._region,
            )
        else:
            print("[INFO] RDS not directly reachable. Starting bastion tunnel...")
            self._tunnel = _BastionTunnel(
                environment_id=self._environment_id,
                db_host=env.db_host,
                region=self._region,
            )
            self._tunnel.start()
            self._db = DatabaseConnection(
                secret_name=env.secret_name,
                host="127.0.0.1",
                port=self._tunnel.LOCAL_PORT,
                region=self._region,
            )

        self._tenant_manager = TenantManager(self._db)
        return self

    def __exit__(self, *args):
        if self._db:
            self._db.close()
        if self._tunnel:
            self._tunnel.stop()
            self._tunnel = None

    def connect(self):
        """Explicit connect for REPL sessions. Pair with close() when done."""
        self.__enter__()

    def close(self):
        """Explicit close for REPL sessions. Closes DB connection, stops tunnel, shuts down bastion."""
        self.__exit__(None, None, None)

    def _require_context(self):
        if self._db is None:
            raise RuntimeError(
                "EquihaxClient must be used as a context manager:\n"
                "  with EquihaxClient(environment_id=...) as client:"
            )

    # -------------------------------------------------------------------------
    # Tenant-scoped access
    # -------------------------------------------------------------------------

    def tenant(self, subdomain: str) -> TenantClient:
        """Return a TenantClient scoped to the given subdomain."""
        self._require_context()
        t = self._tenant_manager.get_tenant(subdomain)
        if not t:
            raise ValueError(f"Tenant '{subdomain}' not found.")
        return TenantClient(tenant=t, db=self._db)

    # -------------------------------------------------------------------------
    # Tenant lifecycle operations
    # -------------------------------------------------------------------------

    def provision_tenant(self, subdomain: str, display_name: str, tier: str = "free") -> Tenant:
        """Provision a new tenant. Raises CapacityError if environment is full."""
        self._require_context()
        capacity = self.get_capacity()

        if capacity["is_full"]:
            active = self._env_manager.get_active_environment()
            if active:
                raise CapacityError(
                    f"Environment '{self._environment.environment_id}' is full "
                    f"({capacity['tenant_count']}/{capacity['threshold']} tenants). "
                    f"Switch to EquihaxClient(environment_id='{active.environment_id}') to provision new tenants."
                )
            raise CapacityError(
                f"Environment '{self._environment.environment_id}' is full "
                f"({capacity['tenant_count']}/{capacity['threshold']} tenants). "
                "All environments are at capacity — call deploy_environment() to provision a new one."
            )

        if capacity["warning"]:
            print(f"[WARN] {capacity['warning']}")

        tenant = self._tenant_manager.provision_tenant(subdomain, display_name, tier)
        try:
            self._env_manager.increment_tenant_count(self._environment.environment_id)
        except Exception as e:
            print(f"[WARN] Tenant provisioned but failed to update environment count: {e}")
        return tenant

    def deprovision_tenant(self, subdomain: str):
        """Permanently remove a tenant and drop their schema."""
        self._require_context()
        self._tenant_manager.deprovision_tenant(subdomain)
        try:
            self._env_manager.decrement_tenant_count(self._environment.environment_id)
        except Exception as e:
            print(f"[WARN] Tenant deprovisioned but failed to update environment count: {e}")

    def suspend_tenant(self, subdomain: str):
        """Suspend a tenant without deleting their data."""
        self._require_context()
        self._tenant_manager.suspend_tenant(subdomain)

    def reactivate_tenant(self, subdomain: str):
        """Reactivate a suspended tenant."""
        self._require_context()
        self._tenant_manager.reactivate_tenant(subdomain)

    def list_tenants(self, status: str = "active") -> list[Tenant]:
        """List all tenants. Defaults to active tenants only."""
        self._require_context()
        return self._tenant_manager.list_tenants(status)

    def get_tenant(self, subdomain: str) -> Optional[Tenant]:
        """Get a single tenant by subdomain."""
        self._require_context()
        return self._tenant_manager.get_tenant(subdomain)

    # -------------------------------------------------------------------------
    # Capacity and environment operations
    # -------------------------------------------------------------------------

    def get_capacity(self) -> dict:
        """Returns current tenant count and capacity status for this environment."""
        self._require_context()
        count = self._tenant_manager.get_count()
        remaining = TENANT_CAPACITY_THRESHOLD - count
        is_full = count >= TENANT_CAPACITY_THRESHOLD
        warning = None

        if remaining <= 10 and not is_full:
            warning = (
                f"Environment '{self._environment.environment_id}' is approaching capacity "
                f"({count}/{TENANT_CAPACITY_THRESHOLD}). "
                "Call deploy_environment() to provision a new one."
            )

        return {
            "environment_id": self._environment.environment_id,
            "tenant_count": count,
            "threshold": TENANT_CAPACITY_THRESHOLD,
            "remaining": remaining,
            "is_full": is_full,
            "warning": warning,
        }

    def deploy_environment(self, environment_id: str, account: str) -> Environment:
        """Deploy a new AWS environment via CDK."""
        return self._env_manager.deploy_environment(environment_id, account)

    def list_environments(self) -> list[Environment]:
        """List all registered environments."""
        return self._env_manager.list_environments()


class CapacityError(Exception):
    """Raised when an environment has reached its tenant capacity threshold."""
    pass
