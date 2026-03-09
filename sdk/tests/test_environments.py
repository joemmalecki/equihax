import pytest
from unittest.mock import MagicMock, patch, call
from equihax.environments import EnvironmentManager, Environment


def make_environment_item(environment_id="prod-1", tenant_count=50):
    return {
        "environment_id": environment_id,
        "db_host": "db.example.com",
        "secret_name": f"equihax/{environment_id}/db/credentials",
        "region": "us-east-1",
        "tenant_count": tenant_count,
        "status": "active",
    }


@pytest.fixture
def mock_table():
    return MagicMock()


@pytest.fixture
def manager(mock_table):
    with patch("equihax.environments.boto3") as mock_boto3:
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value.describe_table.return_value = {}
        mgr = EnvironmentManager(region="us-east-1")
        mgr._table = mock_table
        yield mgr


# -----------------------------------------------------------------------------
# Get and list
# -----------------------------------------------------------------------------

class TestGetEnvironment:
    def test_returns_environment_when_found(self, manager, mock_table):
        mock_table.get_item.return_value = {"Item": make_environment_item()}
        env = manager.get_environment("prod-1")
        assert env.environment_id == "prod-1"
        assert env.db_host == "db.example.com"
        assert env.tenant_count == 50

    def test_returns_none_when_not_found(self, manager, mock_table):
        mock_table.get_item.return_value = {}
        env = manager.get_environment("ghost")
        assert env is None


class TestListEnvironments:
    def test_returns_all_environments(self, manager, mock_table):
        mock_table.scan.return_value = {
            "Items": [
                make_environment_item("prod-1", 80),
                make_environment_item("prod-2", 10),
            ]
        }
        envs = manager.list_environments()
        assert len(envs) == 2
        assert envs[0].environment_id == "prod-1"
        assert envs[1].environment_id == "prod-2"

    def test_returns_empty_list_when_none(self, manager, mock_table):
        mock_table.scan.return_value = {"Items": []}
        assert manager.list_environments() == []


class TestGetActiveEnvironment:
    def test_returns_environment_with_capacity(self, manager, mock_table):
        mock_table.scan.return_value = {"Items": [make_environment_item(tenant_count=50)]}
        env = manager.get_active_environment()
        assert env is not None
        assert env.environment_id == "prod-1"

    def test_returns_none_when_all_full(self, manager, mock_table):
        mock_table.scan.return_value = {"Items": [make_environment_item(tenant_count=100)]}
        env = manager.get_active_environment()
        assert env is None


# -----------------------------------------------------------------------------
# Deploy
# -----------------------------------------------------------------------------

class TestDeployEnvironment:
    def test_raises_when_environment_already_exists(self, manager, mock_table):
        mock_table.get_item.return_value = {"Item": make_environment_item()}
        with pytest.raises(ValueError, match="already exists"):
            manager.deploy_environment("prod-1", account="123456789012")

    def test_raises_when_cdk_fails(self, manager, mock_table):
        mock_table.get_item.return_value = {}
        mock_table.scan.return_value = {"Items": []}
        with patch("equihax.environments.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "CDK error"
            with pytest.raises(RuntimeError, match="CDK deploy failed"):
                manager.deploy_environment("prod-1", account="123456789012")

    def test_registers_environment_after_successful_deploy(self, manager, mock_table):
        mock_table.get_item.return_value = {}
        mock_table.scan.return_value = {"Items": []}
        with patch("equihax.environments.subprocess.run") as mock_run, \
             patch("equihax.environments.EnvironmentManager._parse_cdk_outputs") as mock_outputs, \
             patch("equihax.environments.DatabaseConnection") as mock_db_cls, \
             patch("equihax.environments._BastionTunnel") as mock_tunnel_cls, \
             patch("equihax.environments.socket.create_connection", side_effect=OSError):
            mock_run.return_value.returncode = 0
            mock_outputs.return_value = {"db_endpoint": "db.example.com"}
            manager.deploy_environment("prod-1", account="123456789012")
            mock_table.put_item.assert_called_once()

    def test_deploy_dns_true_for_first_environment(self, manager, mock_table):
        mock_table.get_item.return_value = {}
        mock_table.scan.return_value = {"Items": []}
        with patch("equihax.environments.subprocess.run") as mock_run, \
             patch("equihax.environments.EnvironmentManager._parse_cdk_outputs") as mock_outputs, \
             patch("equihax.environments.DatabaseConnection"), \
             patch("equihax.environments._BastionTunnel"), \
             patch("equihax.environments.socket.create_connection", side_effect=OSError):
            mock_run.return_value.returncode = 0
            mock_outputs.return_value = {"db_endpoint": "db.example.com"}
            manager.deploy_environment("prod-1", account="123456789012")
            cmd = mock_run.call_args[0][0]
            assert "--context" in cmd
            dns_idx = cmd.index("deploy_dns=true") if "deploy_dns=true" in " ".join(cmd) else -1
            assert any("deploy_dns=true" in arg for arg in cmd)

    def test_deploy_dns_false_for_subsequent_environments(self, manager, mock_table):
        mock_table.get_item.return_value = {}
        mock_table.scan.return_value = {"Items": [make_environment_item("prod-1")]}
        with patch("equihax.environments.subprocess.run") as mock_run, \
             patch("equihax.environments.EnvironmentManager._parse_cdk_outputs") as mock_outputs, \
             patch("equihax.environments.DatabaseConnection"), \
             patch("equihax.environments._BastionTunnel"), \
             patch("equihax.environments.socket.create_connection", side_effect=OSError):
            mock_run.return_value.returncode = 0
            mock_outputs.return_value = {"db_endpoint": "db.example.com"}
            manager.deploy_environment("prod-2", account="123456789012")
            cmd = mock_run.call_args[0][0]
            assert any("deploy_dns=false" in arg for arg in cmd)


# -----------------------------------------------------------------------------
# Tenant count
# -----------------------------------------------------------------------------

class TestTenantCount:
    def test_increments_tenant_count(self, manager, mock_table):
        manager.increment_tenant_count("prod-1")
        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert "tenant_count + :val" in call_kwargs["UpdateExpression"]

    def test_decrements_tenant_count(self, manager, mock_table):
        manager.decrement_tenant_count("prod-1")
        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert "tenant_count - :val" in call_kwargs["UpdateExpression"]
