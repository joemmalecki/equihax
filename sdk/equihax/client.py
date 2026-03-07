from .db import DatabaseConnection
from .tenants import TenantManager, Tenant
from .environments import EnvironmentManager, Environment
from typing import Optional


class EquihaxClient:
    """
    Main entry point for the Equihax SDK.

    Manages tenant provisioning and environment lifecycle
    for the Equihax multi-tenant platform.

    Usage:
        client = EquihaxClient(environment_id="prod-1")

        # Provision a new tenant
        client.provision_tenant("acme", display_name="Acme Corp", tier="pro")

        # List all active tenants
        client.list_tenants()

        # Check capacity — warns if approaching 100 tenants
        client.get_capacity()

        # Deploy a new environment when capacity is reached
        client.deploy_environment("prod-2", account="123456789012")
    """

    def __init__(self, environment_id: str, region: str = "us-east-1"):
        self._env_manager = EnvironmentManager(region=region)
        self._region = region

        env = self._env_manager.get_environment(environment_id)
        if not env:
            raise ValueError(
                f"Environment '{environment_id}' not found. "
                "Run deploy_environment() to create it first."
            )

        self._environment = env
        self._db = DatabaseConnection(
            secret_name=env.secret_name,
            host=env.db_host,
            region=region
        )
        self._tenant_manager = TenantManager(self._db)

    # -------------------------------------------------------------------------
    # Tenant operations
    # -------------------------------------------------------------------------

    def provision_tenant(self, subdomain: str, display_name: str, tier: str = "free") -> Tenant:
        """
        Provision a new tenant. Raises CapacityError if environment is full.
        Auto-flags when approaching capacity threshold.
        """
        capacity = self.get_capacity()

        if capacity["is_full"]:
            raise CapacityError(
                f"Environment '{self._environment.environment_id}' is full "
                f"({capacity['tenant_count']}/{capacity['threshold']} tenants). "
                "Call deploy_environment() to provision a new environment."
            )

        if capacity["warning"]:
            print(f"[WARN] {capacity['warning']}")

        tenant = self._tenant_manager.provision_tenant(subdomain, display_name, tier)
        self._env_manager.increment_tenant_count(self._environment.environment_id)
        return tenant

    def deprovision_tenant(self, subdomain: str):
        """Permanently remove a tenant and drop their schema."""
        self._tenant_manager.deprovision_tenant(subdomain)
        self._env_manager.decrement_tenant_count(self._environment.environment_id)

    def suspend_tenant(self, subdomain: str):
        """Suspend a tenant without deleting their data."""
        self._tenant_manager.suspend_tenant(subdomain)

    def reactivate_tenant(self, subdomain: str):
        """Reactivate a suspended tenant."""
        self._tenant_manager.reactivate_tenant(subdomain)

    def list_tenants(self, status: str = "active") -> list[Tenant]:
        """List all tenants. Defaults to active tenants only."""
        return self._tenant_manager.list_tenants(status)

    def get_tenant(self, subdomain: str) -> Optional[Tenant]:
        """Get a single tenant by subdomain."""
        return self._tenant_manager.get_tenant(subdomain)

    # -------------------------------------------------------------------------
    # Capacity and environment operations
    # -------------------------------------------------------------------------

    def get_capacity(self) -> dict:
        """
        Returns current tenant count and capacity status for this environment.
        Emits a warning when within 10 tenants of the threshold.
        """
        from .environments import TENANT_CAPACITY_THRESHOLD
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
            "warning": warning
        }

    def deploy_environment(self, environment_id: str, account: str) -> Environment:
        """
        Manually deploy a new AWS environment via CDK.
        Call this after receiving a capacity warning from get_capacity()
        or provision_tenant().
        """
        return self._env_manager.deploy_environment(environment_id, account)

    def list_environments(self) -> list[Environment]:
        """List all registered environments."""
        return self._env_manager.list_environments()


class CapacityError(Exception):
    """Raised when an environment has reached its tenant capacity threshold."""
    pass
