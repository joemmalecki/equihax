import pytest
from unittest.mock import MagicMock, patch
from equihax.client import EquihaxClient, CapacityError
from equihax.environments import Environment


def make_environment(tenant_count=0):
    return Environment(
        environment_id="prod-1",
        db_host="db.example.com",
        secret_name="equihax/prod-1/db/credentials",
        region="us-east-1",
        tenant_count=tenant_count,
        status="active"
    )


@pytest.fixture
def client():
    with patch("equihax.client.EnvironmentManager") as mock_env_mgr_cls, \
         patch("equihax.client.DatabaseConnection") as mock_db_cls, \
         patch("equihax.client.TenantManager") as mock_tenant_mgr_cls:

        mock_env_mgr = mock_env_mgr_cls.return_value
        mock_env_mgr.get_environment.return_value = make_environment()

        c = EquihaxClient(environment_id="prod-1")
        c._env_manager = mock_env_mgr
        c._tenant_manager = mock_tenant_mgr_cls.return_value
        yield c


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
        assert capacity["warning"] is None  # full, not warning


class TestProvisionTenant:
    def test_provisions_when_capacity_available(self, client):
        client._tenant_manager.get_count.return_value = 50
        client._tenant_manager.provision_tenant.return_value = MagicMock()
        client.provision_tenant("acme", "Acme Corp")
        client._tenant_manager.provision_tenant.assert_called_once_with("acme", "Acme Corp", "free")
        client._env_manager.increment_tenant_count.assert_called_once_with("prod-1")

    def test_raises_capacity_error_when_full(self, client):
        client._tenant_manager.get_count.return_value = 100
        with pytest.raises(CapacityError):
            client.provision_tenant("acme", "Acme Corp")

    def test_prints_warning_when_near_capacity(self, client, capsys):
        client._tenant_manager.get_count.return_value = 95
        client._tenant_manager.provision_tenant.return_value = MagicMock()
        client.provision_tenant("acme", "Acme Corp")
        captured = capsys.readouterr()
        assert "approaching capacity" in captured.out


class TestDeprovisionTenant:
    def test_deprovisions_and_decrements(self, client):
        client.deprovision_tenant("acme")
        client._tenant_manager.deprovision_tenant.assert_called_once_with("acme")
        client._env_manager.decrement_tenant_count.assert_called_once_with("prod-1")


class TestListTenants:
    def test_delegates_to_tenant_manager(self, client):
        client._tenant_manager.list_tenants.return_value = []
        result = client.list_tenants()
        client._tenant_manager.list_tenants.assert_called_once_with("active")
        assert result == []

    def test_passes_status_filter(self, client):
        client._tenant_manager.list_tenants.return_value = []
        client.list_tenants(status="suspended")
        client._tenant_manager.list_tenants.assert_called_once_with("suspended")
