# Equihax

Multi-tenant SaaS platform monorepo.

## Structure

```
equihax/
├── infra/       # CDK — provisions AWS environments
├── app/         # nginx + Apache/PHP web application
└── sdk/         # Python SDK — tenant and environment management
```

## Quick Start

```bash
# Deploy infrastructure
cd infra && cdk deploy --all --context account=YOUR_ACCOUNT_ID

# Install SDK
pip install equihax --index-url https://YOUR_CODEARTIFACT_URL/simple/

# Provision a tenant
python3 -c "
from equihax import EquihaxClient
client = EquihaxClient(environment='prod-1')
client.provision_tenant('acme', display_name='Acme Corp', tier='pro')
"
```

## Components

- [Infrastructure](./infra/README.md)
- [Application](./app/README.md)
- [SDK](./sdk/README.md)
