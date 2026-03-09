import pytest
from unittest.mock import MagicMock, call
from equihax.tenants import TenantManager, Tenant, RESERVED_SUBDOMAINS


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def manager(mock_db):
    return TenantManager(db=mock_db)


def make_tenant_row(subdomain="acme", status="active"):
    return {
        "id": 1,
        "schema_name": subdomain.replace("-", "_"),
        "subdomain": subdomain,
        "display_name": "Acme Corp",
        "tier": "pro",
        "status": status,
        "created_at": "2024-01-01 00:00:00",
        "updated_at": "2024-01-01 00:00:00",
    }


class TestListTenants:
    def test_returns_active_tenants(self, manager, mock_db):
        mock_db.query.return_value = [make_tenant_row()]
        tenants = manager.list_tenants()
        assert len(tenants) == 1
        assert tenants[0].subdomain == "acme"

    def test_passes_status_filter(self, manager, mock_db):
        mock_db.query.return_value = []
        manager.list_tenants(status="suspended")
        mock_db.query.assert_called_once_with(
            "SELECT * FROM tenants WHERE status = %s ORDER BY created_at DESC",
            ("suspended",)
        )


class TestGetTenant:
    def test_returns_tenant_when_found(self, manager, mock_db):
        mock_db.query_one.return_value = make_tenant_row()
        tenant = manager.get_tenant("acme")
        assert tenant.subdomain == "acme"
        assert tenant.schema_name == "acme"

    def test_returns_none_when_not_found(self, manager, mock_db):
        mock_db.query_one.return_value = None
        tenant = manager.get_tenant("ghost")
        assert tenant is None

    def test_hyphen_subdomain_maps_to_underscore_schema(self, manager, mock_db):
        mock_db.query_one.return_value = make_tenant_row("coca-cola")
        tenant = manager.get_tenant("coca-cola")
        assert tenant.schema_name == "coca_cola"


class TestProvisionTenant:
    def test_provisions_successfully(self, manager, mock_db):
        # First call (existence check) returns None, second call (after insert) returns row
        mock_db.query_one.side_effect = [None, make_tenant_row()]
        tenant = manager.provision_tenant("acme", "Acme Corp", "pro")
        assert tenant.subdomain == "acme"

    def test_raises_if_tenant_already_exists(self, manager, mock_db):
        mock_db.query_one.return_value = make_tenant_row()
        with pytest.raises(ValueError, match="already exists"):
            manager.provision_tenant("acme", "Acme Corp")

    def test_raises_on_reserved_subdomain(self, manager, mock_db):
        for reserved in ["www", "admin", "api"]:
            with pytest.raises(ValueError, match="reserved"):
                manager.provision_tenant(reserved, "Test")

    def test_raises_on_invalid_subdomain_format(self, manager, mock_db):
        invalid = ["-acme", "acme-", "acme corp", "ACME", "acme!"]
        for subdomain in invalid:
            with pytest.raises(ValueError, match="Invalid subdomain"):
                manager.provision_tenant(subdomain, "Test")

    def test_creates_schema_with_underscores(self, manager, mock_db):
        mock_db.query_one.side_effect = [None, make_tenant_row("coca-cola")]
        manager.provision_tenant("coca-cola", "Coca Cola")
        create_call = mock_db.execute.call_args_list[0]
        assert "coca_cola" in create_call[0][0]

    def test_registers_tenant_in_registry(self, manager, mock_db):
        mock_db.query_one.side_effect = [None, make_tenant_row()]
        manager.provision_tenant("acme", "Acme Corp")
        calls = [str(c) for c in mock_db.execute.call_args_list]
        assert any("INSERT" in c for c in calls)

    def test_runs_migrations_via_execute_script(self, manager, mock_db):
        mock_db.query_one.side_effect = [None, make_tenant_row()]
        manager.provision_tenant("acme", "Acme Corp")
        mock_db.execute_script.assert_called_once()
        call_kwargs = mock_db.execute_script.call_args[1]
        assert call_kwargs["database"] == "acme"


class TestDeprovisionTenant:
    def test_deprovisions_successfully(self, manager, mock_db):
        mock_db.query_one.return_value = make_tenant_row()
        manager.deprovision_tenant("acme")
        calls = [str(c) for c in mock_db.execute.call_args_list]
        assert any("DROP DATABASE" in c for c in calls)
        assert any("DELETE" in c for c in calls)

    def test_raises_if_tenant_not_found(self, manager, mock_db):
        mock_db.query_one.return_value = None
        with pytest.raises(ValueError, match="not found"):
            manager.deprovision_tenant("ghost")


class TestReactivateTenant:
    def test_reactivates_suspended_tenant(self, manager, mock_db):
        mock_db.query_one.return_value = make_tenant_row(status="suspended")
        manager.reactivate_tenant("acme")
        calls = [str(c) for c in mock_db.execute.call_args_list]
        assert any("active" in c for c in calls)

    def test_raises_if_tenant_not_found(self, manager, mock_db):
        mock_db.query_one.return_value = None
        with pytest.raises(ValueError, match="not found"):
            manager.reactivate_tenant("ghost")


class TestSuspendTenant:
    def test_suspends_active_tenant(self, manager, mock_db):
        mock_db.query_one.return_value = make_tenant_row()
        manager.suspend_tenant("acme")
        calls = [str(c) for c in mock_db.execute.call_args_list]
        assert any("suspended" in c for c in calls)

    def test_raises_if_tenant_not_found(self, manager, mock_db):
        mock_db.query_one.return_value = None
        with pytest.raises(ValueError, match="not found"):
            manager.suspend_tenant("ghost")


class TestValidateSubdomain:
    def test_valid_subdomains(self, manager, mock_db):
        valid = ["acme", "coca-cola", "my-company", "abc123", "a1b2c3"]
        for subdomain in valid:
            manager._validate_subdomain(subdomain)  # should not raise

    def test_rejects_reserved(self, manager, mock_db):
        with pytest.raises(ValueError, match="reserved"):
            manager._validate_subdomain("admin")

    def test_rejects_leading_hyphen(self, manager, mock_db):
        with pytest.raises(ValueError):
            manager._validate_subdomain("-acme")

    def test_rejects_trailing_hyphen(self, manager, mock_db):
        with pytest.raises(ValueError):
            manager._validate_subdomain("acme-")
