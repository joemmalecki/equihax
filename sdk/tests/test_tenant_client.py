import pytest
from unittest.mock import MagicMock
from equihax.tenant_client import TenantClient
from equihax.tenants import Tenant


def make_tenant(subdomain="acme", schema_name="acme"):
    return Tenant(
        id=1,
        schema_name=schema_name,
        subdomain=subdomain,
        display_name="Acme Corp",
        tier="pro",
        status="active",
        created_at="2024-01-01 00:00:00",
        updated_at="2024-01-01 00:00:00",
    )


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def tenant_client(mock_db):
    return TenantClient(tenant=make_tenant(), db=mock_db)


# -----------------------------------------------------------------------------
# Info
# -----------------------------------------------------------------------------

class TestInfo:
    def test_returns_tenant_object(self, tenant_client):
        assert tenant_client.info.subdomain == "acme"
        assert tenant_client.info.schema_name == "acme"
        assert tenant_client.info.display_name == "Acme Corp"


# -----------------------------------------------------------------------------
# Messages
# -----------------------------------------------------------------------------

class TestGetMessages:
    def test_queries_messages_in_tenant_schema(self, tenant_client, mock_db):
        mock_db.query.return_value = []
        tenant_client.get_messages()
        mock_db.query.assert_called_once_with(
            "SELECT * FROM messages ORDER BY created_at DESC",
            database="acme",
        )

    def test_returns_messages(self, tenant_client, mock_db):
        mock_db.query.return_value = [
            {"id": 1, "message": "Hello", "created_at": "2024-01-01"}
        ]
        result = tenant_client.get_messages()
        assert len(result) == 1
        assert result[0]["message"] == "Hello"


class TestSaveMessage:
    def test_inserts_into_tenant_schema(self, tenant_client, mock_db):
        tenant_client.save_message("Hello!")
        mock_db.execute.assert_called_once_with(
            "INSERT INTO messages (message) VALUES (%s)",
            ("Hello!",),
            database="acme",
        )


# -----------------------------------------------------------------------------
# Ad-hoc queries
# -----------------------------------------------------------------------------

class TestAdHocQueries:
    def test_query_scoped_to_tenant_schema(self, tenant_client, mock_db):
        mock_db.query.return_value = []
        tenant_client.query("SELECT * FROM orders WHERE status = %s", ("pending",))
        mock_db.query.assert_called_once_with(
            "SELECT * FROM orders WHERE status = %s",
            ("pending",),
            database="acme",
        )

    def test_query_one_scoped_to_tenant_schema(self, tenant_client, mock_db):
        mock_db.query_one.return_value = None
        tenant_client.query_one("SELECT * FROM orders WHERE id = %s", (1,))
        mock_db.query_one.assert_called_once_with(
            "SELECT * FROM orders WHERE id = %s",
            (1,),
            database="acme",
        )

    def test_execute_scoped_to_tenant_schema(self, tenant_client, mock_db):
        tenant_client.execute("UPDATE orders SET status = %s WHERE id = %s", ("shipped", 1))
        mock_db.execute.assert_called_once_with(
            "UPDATE orders SET status = %s WHERE id = %s",
            ("shipped", 1),
            database="acme",
        )

    def test_hyphen_subdomain_scoped_to_underscore_schema(self, mock_db):
        client = TenantClient(tenant=make_tenant("coca-cola", "coca_cola"), db=mock_db)
        mock_db.query.return_value = []
        client.query("SELECT 1")
        call_kwargs = mock_db.query.call_args[1]
        assert call_kwargs["database"] == "coca_cola"
