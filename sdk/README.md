# Equihax SDK

Python SDK for managing tenants and environments on the Equihax platform.

## Installation

```bash
pip install equihax --index-url https://YOUR_ACCOUNT.d.codeartifact.us-east-1.amazonaws.com/pypi/equihax/simple/
```

## Usage

```python
from equihax import EquihaxClient

client = EquihaxClient(environment_id="prod-1")

# Provision a new tenant
tenant = client.provision_tenant("acme", display_name="Acme Corp", tier="pro")
print(f"Tenant live at https://acme.equihax.net")

# List all active tenants
tenants = client.list_tenants()

# Check capacity
capacity = client.get_capacity()
# {
#   "environment_id": "prod-1",
#   "tenant_count": 87,
#   "threshold": 100,
#   "remaining": 13,
#   "is_full": False,
#   "warning": "Environment 'prod-1' is approaching capacity..."
# }

# When you receive a warning, deploy a new environment
client.deploy_environment("prod-2", account="123456789012")

# Suspend a tenant (keeps data, blocks access)
client.suspend_tenant("acme")

# Reactivate
client.reactivate_tenant("acme")

# Permanently remove a tenant
client.deprovision_tenant("acme")
```

## Capacity Management

Each environment supports up to 100 active tenants. The SDK:

- **Auto-flags** at 90 tenants — `provision_tenant()` and `get_capacity()` emit a warning
- **Blocks** at 100 tenants — `provision_tenant()` raises `CapacityError`
- **Manual confirm** — call `deploy_environment()` explicitly to provision a new AWS stack

```python
from equihax import EquihaxClient
from equihax.client import CapacityError

client = EquihaxClient(environment_id="prod-1")

try:
    client.provision_tenant("newclient", "New Client Inc")
except CapacityError:
    # Deploy a new environment and provision there
    client.deploy_environment("prod-2", account="123456789012")
    prod2 = EquihaxClient(environment_id="prod-2")
    prod2.provision_tenant("newclient", "New Client Inc")
```

## Running Tests

```bash
cd sdk
pip install -e ".[dev]"
pytest tests/ -v
```

## Publishing to CodeArtifact

```bash
# Authenticate
aws codeartifact login --tool pip --repository equihax --domain equihax --domain-owner YOUR_ACCOUNT_ID

# Build and publish
python setup.py sdist bdist_wheel
twine upload --repository codeartifact dist/*
```
