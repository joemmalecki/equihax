import pytest
from unittest.mock import MagicMock, patch
from equihax.client import EquihaxClient, CapacityError
from equihax.environments import Environment
from equihax.tenant_client import TenantClient
from equihax.tenants import Tenant


def make_environment(tenant_count=50):
    return Environment(
        environment_id="prod-1",
        db_host="db.example.com",
        secret_name="equihax/prod-1/db/credentials",
        region="us-east-1",
        tenant_count=tenant_count,
        status="active"
    )


def make_tenant():
    return Tenant(
        id=1,
        schema_name="acme",
        subdomain="acme",
        display_name="Acme Corp",
        tier="pro",
        status="active",
        created_at="2024-01-01 00:00:00",
        updated_at="2024-01-01 00:00:00",
    )


@pytest.fixture
def client():
    with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls, \
         patch("equihax.client.DatabaseConnection"), \
         patch("equihax.client.TenantManager") as mock_tenant_mgr_cls, \
         patch("equihax.client._can_reach_db", return_value=True):

        mock_env_mgr_cls.return_value.get_environment.return_value = make_environment()

        with EquihaxClient(environment_id="prod-1") as c:
            c._tenant_manager = mock_tenant_mgr_cls.return_value
            c._env_manager = mock_env_mgr_cls.return_value
            yield c


# -----------------------------------------------------------------------------
# Context manager and connection
# -----------------------------------------------------------------------------

class TestContextManager:
    def test_connects_directly_when_db_reachable(self):
        with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls, \
             patch("equihax.client.DatabaseConnection") as mock_db_cls, \
             patch("equihax.client.TenantManager"), \
             patch("equihax.client._can_reach_db", return_value=True):
            mock_env_mgr_cls.return_value.get_environment.return_value = make_environment()
            with EquihaxClient(environment_id="prod-1"):
                args = mock_db_cls.call_args[1]
                assert args["host"] == "db.example.com"

    def test_starts_tunnel_when_db_unreachable(self):
        with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls, \
             patch("equihax.client.DatabaseConnection") as mock_db_cls, \
             patch("equihax.client.TenantManager"), \
             patch("equihax.client._BastionTunnel") as mock_tunnel_cls, \
             patch("equihax.client._can_reach_db", return_value=False):
            mock_tunnel_cls.return_value.LOCAL_PORT = 13306
            mock_env_mgr_cls.return_value.get_environment.return_value = make_environment()
            with EquihaxClient(environment_id="prod-1"):
                mock_tunnel_cls.return_value.start.assert_called_once()
                args = mock_db_cls.call_args[1]
                assert args["host"] == "127.0.0.1"
                assert args["port"] == 13306

    def test_closes_db_and_stops_tunnel_on_exit(self):
        with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls, \
             patch("equihax.client.DatabaseConnection") as mock_db_cls, \
             patch("equihax.client.TenantManager"), \
             patch("equihax.client._BastionTunnel") as mock_tunnel_cls, \
             patch("equihax.client._can_reach_db", return_value=False):
            mock_env_mgr_cls.return_value.get_environment.return_value = make_environment()
            with EquihaxClient(environment_id="prod-1"):
                pass
            mock_db_cls.return_value.close.assert_called_once()
            mock_tunnel_cls.return_value.stop.assert_called_once()

    def test_raises_when_environment_not_found(self):
        with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls:
            mock_env_mgr_cls.return_value.get_environment.return_value = None
            with pytest.raises(ValueError, match="not found"):
                with EquihaxClient(environment_id="prod-1"):
                    pass

    def test_requires_context_for_db_operations(self):
        with patch("equihax.client.EnvironmentManager"):
            client = EquihaxClient(environment_id="prod-1")
            with pytest.raises(RuntimeError, match="context manager"):
                client.list_tenants()

    def test_connect_and_close_for_repl(self):
        with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls, \
             patch("equihax.client.DatabaseConnection") as mock_db_cls, \
             patch("equihax.client.TenantManager"), \
             patch("equihax.client._can_reach_db", return_value=True):
            mock_env_mgr_cls.return_value.get_environment.return_value = make_environment()
            client = EquihaxClient(environment_id="prod-1")
            client.connect()
            client.close()
            mock_db_cls.return_value.close.assert_called_once()


# -----------------------------------------------------------------------------
# Tenant scoped access
# -----------------------------------------------------------------------------

class TestTenant:
    def test_returns_tenant_client(self, client):
        client._tenant_manager.get_tenant.return_value = make_tenant()
        result = client.tenant("acme")
        assert isinstance(result, TenantClient)
        assert result.info.subdomain == "acme"

    def test_raises_when_tenant_not_found(self, client):
        client._tenant_manager.get_tenant.return_value = None
        with pytest.raises(ValueError, match="not found"):
            client.tenant("ghost")


# -----------------------------------------------------------------------------
# Capacity
# -----------------------------------------------------------------------------

class TestGetCapacity:
    def test_returns_count_and_threshold(self, client):
        client._tenant_manager.get_count.return_value = 50
        capacity = client.get_capacity()
        assert capacity["tenant_count"] == 50
        assert capacity["threshold"] == 100
        assert capacity["remaining"] == 50
        assert capacity["is_full"] is False
        assert capacity["warning"] is None

    def test_warns_when_within_10_of_threshold(self, client):
        client._tenant_manager.get_count.return_value = 92
        capacity = client.get_capacity()
        assert capacity["warning"] is not None
        assert "approaching capacity" in capacity["warning"]

    def test_is_full_at_threshold(self, client):
        client._tenant_manager.get_count.return_value = 100
        capacity = client.get_capacity()
        assert capacity["is_full"] is True
        assert capacity["warning"] is None


# -----------------------------------------------------------------------------
# Tenant lifecycle
# -----------------------------------------------------------------------------

class TestProvisionTenant:
    def test_provisions_when_capacity_available(self, client):
        client._tenant_manager.get_count.return_value = 50
        client._tenant_manager.provision_tenant.return_value = make_tenant()
        client.provision_tenant("acme", "Acme Corp")
        client._tenant_manager.provision_tenant.assert_called_once_with("acme", "Acme Corp", "free")
        client._env_manager.increment_tenant_count.assert_called_once_with("prod-1")

    def test_raises_capacity_error_when_full(self, client):
        client._tenant_manager.get_count.return_value = 100
        client._env_manager.get_active_environment.return_value = None
        with pytest.raises(CapacityError):
            client.provision_tenant("acme", "Acme Corp")

    def test_capacity_error_suggests_active_environment(self, client):
        client._tenant_manager.get_count.return_value = 100
        client._env_manager.get_active_environment.return_value = make_environment()
        with pytest.raises(CapacityError, match="prod-1"):
            client.provision_tenant("acme", "Acme Corp")

    def test_prints_warning_when_near_capacity(self, client, capsys):
        client._tenant_manager.get_count.return_value = 95
        client._tenant_manager.provision_tenant.return_value = make_tenant()
        client.provision_tenant("acme", "Acme Corp")
        assert "approaching capacity" in capsys.readouterr().out


class TestDeprovisionTenant:
    def test_deprovisions_and_decrements(self, client):
        client.deprovision_tenant("acme")
        client._tenant_manager.deprovision_tenant.assert_called_once_with("acme")
        client._env_manager.decrement_tenant_count.assert_called_once_with("prod-1")


class TestSuspendTenant:
    def test_delegates_to_tenant_manager(self, client):
        client.suspend_tenant("acme")
        client._tenant_manager.suspend_tenant.assert_called_once_with("acme")


class TestReactivateTenant:
    def test_delegates_to_tenant_manager(self, client):
        client.reactivate_tenant("acme")
        client._tenant_manager.reactivate_tenant.assert_called_once_with("acme")


class TestListTenants:
    def test_returns_active_tenants_by_default(self, client):
        client._tenant_manager.list_tenants.return_value = []
        client.list_tenants()
        client._tenant_manager.list_tenants.assert_called_once_with("active")

    def test_passes_status_filter(self, client):
        client._tenant_manager.list_tenants.return_value = []
        client.list_tenants(status="suspended")
        client._tenant_manager.list_tenants.assert_called_once_with("suspended")


# -----------------------------------------------------------------------------
# Environment operations
# -----------------------------------------------------------------------------

class TestEnvironmentOperations:
    def test_deploy_environment_delegates(self, client):
        client._env_manager.deploy_environment.return_value = make_environment()
        client.deploy_environment("prod-2", account="123456789012")
        client._env_manager.deploy_environment.assert_called_once_with("prod-2", "123456789012")

    def test_list_environments_delegates(self, client):
        client._env_manager.list_environments.return_value = [make_environment()]
        result = client.list_environments()
        assert len(result) == 1
