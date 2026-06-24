# Cocktail Agent on Azure: Implementation Specification

## 1. Scope and Confirmed Decisions

This specification is based only on decisions already provided.

- Subscription: Visual Studio Professional Subscription
- Subscription ID: f21626e0-e50d-4a92-baa1-daba0d623b49
- Region: West US
- Environment scope: Dev only
- IaC: Bicep
- MCP server stack: Python
- Database: Azure Database for PostgreSQL Flexible Server
- MCP access model: private access with API key stored in Key Vault
- Networking for MVP: Public endpoints
- Scraper trigger model (MVP): Manual on-demand only
- Phase 3 queue service: Azure Service Bus
- CI/CD: GitHub Actions
- Repository: awjohns4/cocktails-project
- Container registry: Azure Container Registry (ACR)
- Required tag on all Azure resources:
  - Owner: adam.johns@neudesic.com
- Budget target: <= $50/month
- SLA/SLO target: none specified

## 2. Open Items by Phase

### 2.1 Phase 1

- None

### 2.2 Phase 2

- None

## 3. Resource Group and Naming

### 3.1 Resource Group

Use the naming-standard dev resource group name:

- Resource Group: rg-cocktailagent-dev-wus-01
- Region: westus

### 3.2 Required Tag Policy

Every deployed resource must include:

- Owner=adam.johns@neudesic.com

Bicep modules must apply this tag to all resources.

### 3.3 Naming Convention Standard

Use this default pattern for Azure resources:

- `<rtype>-cocktailagent-<env>-<region>-<nn>`

Field definitions:

- `rtype`: resource type short code
- `env`: environment (`dev`, later `stg`, `prd`)
- `region`: region short code (`wus` for West US)
- `nn`: two-digit sequence (`01`, `02`, ...)

Primary resource type codes:

- `rg`: resource group
- `cae`: container apps environment
- `ca`: container app (MCP API)
- `caj`: container app job (scraper)
- `psql`: PostgreSQL flexible server
- `kv`: Key Vault
- `ai`: Application Insights
- `log`: Log Analytics workspace
- `acr`: Azure Container Registry
- `sbn`: Service Bus namespace (Phase 3)
- `sbt`: Service Bus queue/topic (Phase 3)
- `srch`: Azure AI Search (Phase 2)

Azure naming constraints to enforce:

- ACR name must be alphanumeric only (no hyphens) and globally unique
- Storage account names (if added later) must be lowercase alphanumeric only
- Some resources (including Key Vault and ACR) require global uniqueness

### 3.4 Dev Resource Name Map (West US)

Use these concrete names for Dev unless a uniqueness conflict requires a suffix change:

- Resource Group: `rg-cocktailagent-dev-wus-01`
- Container Apps Environment: `cae-cocktailagent-dev-wus-01`
- MCP Container App: `ca-cocktailagent-mcp-dev-wus-01`
- Scraper Container Apps Job: `caj-cocktailagent-scraper-dev-wus-01`
- PostgreSQL Flexible Server: `psql-cocktailagent-dev-wus-01`
- Key Vault: `kvcocktaildevwus01`
- Application Insights: `ai-cocktailagent-dev-wus-01`
- Log Analytics Workspace: `log-cocktailagent-dev-wus-01`
- Azure Container Registry: `acrcocktailagentdevwus01`

## 4. Phase 1 (MVP) Implementation

## 4.1 Architecture Components

- Azure Container Apps Environment
- Azure Container App: MCP API (Python)
- Azure Container Apps Job: scraper runner (manual trigger only)
- Azure Database for PostgreSQL Flexible Server
- Azure Key Vault
- Azure Application Insights + Log Analytics Workspace
- Azure Container Registry (ACR)

## 4.2 Runtime Flow

1. Client/agent calls MCP API endpoint with API key.
2. MCP API reads cocktail data from PostgreSQL.
3. When data refresh is needed, operator manually triggers scraper job.
4. Scraper job discovers recipe URLs and writes structured sections to PostgreSQL.

## 4.3 Data Layer Requirements

PostgreSQL must contain at minimum:

- pages
  - id
  - url
  - title
  - status
  - scraped_at
- recipe_sections
  - id
  - page_id
  - section_name
  - section_json

Schema migration process:

- Python migration script in repo, executed by CI/CD deploy job.
- Migration must be idempotent.

## 4.4 MCP API Requirements (Phase 1)

Implement Python MCP server tools:

- get_recipe(name_or_id)
- search_cocktails(filters)
- recommend_cocktails(preferences, limit)

Deferred from Phase 1 scope:

- get_similar_cocktails(name_or_id)

Authentication requirement:

- API key required for all MCP endpoints.
- API key value stored in Key Vault.
- MCP app loads key via managed identity or startup secret injection.

## 4.5 Scraper Job Requirements (Phase 1)

- Trigger mode: manual only (no schedule)
- Input parameters:
  - drink_name
  - result_selector (single index or start-end)
- Container Apps Job must support command override to pass parameters.

## 4.6 Observability Requirements

- App Insights enabled for MCP app and scraper job
- Log Analytics workspace linked
- Structured logs required with correlation fields:
  - request_id
  - cocktail_name
  - source_url
  - status

## 4.7 Security Requirements

- Key Vault stores:
  - MCP_API_KEY
  - DB_CONNECTION_STRING or DB credentials
- Public endpoints allowed in MVP (confirmed)
- No secrets committed to repository
- Managed identity preferred for Azure resource access

## 4.8 Cost Guardrails (<= $50/month target)

Use low-cost dev SKUs and scale-to-zero where possible.

Initial guidance:

- Container Apps: min replicas 0 for MCP app if acceptable for dev
- Scraper as job only, no always-on worker
- PostgreSQL Flexible Server: lowest dev burstable SKU
- App Insights retention: short dev retention
- Keep request volume low and test dataset limited

Budget verification step:

- Run Azure cost estimate and review actual spend weekly.

## 5. Phase 2 Implementation (Hybrid Recommendation)

## 5.1 Additional Components

- Azure AI Search
- Azure OpenAI embeddings

### 5.1.1 Phase 2 Confirmed Service Choices

- Embedding provider: Azure OpenAI
- Embedding model: text-embedding-3-small
- Embedding region policy: West US primary, allow secondary Azure region fallback if unavailable
- Secondary embedding region: East US
- Azure AI Search pricing model (Dev): Serverless Developer (Preview)
- Azure AI Search region (Dev): West Central US
- Azure AI Search note: preview service used for cost-efficient, usage-based development workloads
- Search index topology: single unified cocktails index
- Index refresh strategy: manual reindex trigger only (aligned with manual scrape flow)
- Evaluation dataset size: 50 prompts

## 5.2 Phase 2 Data/Retrieval Flow

1. Keep PostgreSQL as source of truth.
2. Build searchable index docs from recipe sections.
3. Query AI Search using hybrid retrieval.
4. Apply metadata filters (strength, sweet/sour, ingredient constraints).
5. Hydrate final response from PostgreSQL canonical record.

### 5.2.1 Indexed Content Scope

Phase 2 index documents include:

- Recipe sections (ingredients, prepare, how_to_make, garnish, strength/taste)
- Review text
- History text

Canonical instructions and structured recipe details must still be served from PostgreSQL.

### 5.2.2 Index Schema Definition (Implemented)

- Index schema file: `infra/search/cocktails-index.json`
- Index name: `cocktails-index`
- Key field: `id`
- Vector field: `searchContentVector` (1536 dimensions for `text-embedding-3-small`)
- Semantic config: `cocktails-semantic-config`
- Provision/apply script: `scripts/create_search_index.sh`

Operational notes:

- Index objects are data-plane resources in Azure AI Search and are applied via Search REST API.
- This schema is versioned in Git and is safe to re-apply (PUT upsert behavior).

## 5.3 Phase 2 MCP Additions

- recommend_cocktails_hybrid(preferences, constraints, limit)
- search_cocktails_semantic(query, filters)
- trigger_reindex() (manual index rebuild)

### 5.3.1 Retrieval Configuration (Initial)

- Hybrid weighting: balanced keyword + vector
- Filtering priority: strength/sweetness/ingredient constraints applied before final ranking
- Reindex trigger access: ops/admin role only

## 5.4 Phase 2 Quality Requirements

- Add evaluation set for recommendation relevance
- Track relevance metrics and query latency
- Ensure deterministic recipe instructions still come from PostgreSQL

### 5.4.1 Recommended Initial Acceptance Thresholds

These thresholds are recommended for Dev Phase 2 acceptance:

- Top-3 relevance >= 70% across 50-prompt evaluation set
- p95 hybrid query latency <= 2.5 seconds
- 0 deterministic-instruction regressions (recipe steps/ingredients must remain PostgreSQL-sourced)

### 5.4.2 Evaluation Dataset Composition (50 Prompts)

- 15 ingredient-based prompts
- 15 flavor-profile prompts
- 10 strength/sweetness prompts
- 10 situational prompts

Generation method:

- Template-generated prompts, then user-reviewed before test execution

### 5.4.3 Staleness Policy

- No staleness policy in Phase 2 (explicitly deferred)

## 6. Phase 3 Implementation (Agent-Triggered Missing-Data Backfill)

## 6.1 Additional Components

- Azure Service Bus (queue + dead-letter handling)
- Scrape request lifecycle table in PostgreSQL
- Worker mode in scraper runtime (consume queue messages)

## 6.2 Phase 3 Flow

1. Agent asks for cocktail not in DB.
2. MCP tool ensure_cocktail_available(name) checks DB.
3. If missing:
  - insert scrape_requests row
  - enqueue message in Service Bus
4. Worker processes message and scrapes data.
5. Worker updates request status.
6. Agent polls get_scrape_status(request_id) until complete.

## 6.3 scrape_requests Schema

Minimum columns:

- request_id (UUID primary key)
- cocktail_name
- status (pending|running|succeeded|failed)
- attempts
- error_message
- created_at
- updated_at

## 6.4 Reliability Controls

- Idempotency: suppress duplicate in-flight requests by cocktail_name
- Retry policy with max attempts
- Dead-letter queue monitoring and manual replay process
- Cooldown policy for repeated requests

## 7. IaC Layout (Bicep)

Recommended file structure:

- infra/
  - main.bicep
  - modules/
    - container-app-env.bicep
    - container-app-mcp.bicep
    - container-app-job-scraper.bicep
    - postgres-flex.bicep
    - keyvault.bicep
    - appinsights.bicep
    - log-analytics.bicep
    - servicebus.bicep (phase 3)
    - ai-search.bicep (phase 2)
  - parameters/
    - dev.bicepparam

IaC requirements:

- Every resource includes Owner tag
- Region parameter default westus
- Dev-only deployment path

## 8. CI/CD Specification (GitHub Actions)

Repository:

- awjohns4/cocktails-project

Workflows to implement:

- ci.yml
  - lint/test for scraper and MCP code
  - build container image(s)
- deploy-dev.yml
  - deploy Bicep to resource group rg-cocktailagent-dev-wus-01
  - run DB migration
  - deploy MCP app
  - deploy scraper job

Secrets/variables in GitHub:

- AZURE_CREDENTIALS (or OIDC-based federation config)
- AZURE_SUBSCRIPTION_ID
- AZURE_TENANT_ID
- AZURE_RESOURCE_GROUP=rg-cocktailagent-dev-wus-01
- POSTGRES_ADMIN_USERNAME
- POSTGRES_ADMIN_PASSWORD
- MCP_API_KEY (optional override; if omitted, deployment workflow auto-generates a key)

Authentication note:

- Current MVP deployment uses `AZURE_CREDENTIALS` for speed.
- Security hardening follow-up: migrate GitHub Actions auth to OIDC federation and remove long-lived Azure credentials from GitHub secrets.

## 9. Manual Operations Runbook (Dev)

## 9.1 Trigger scraper job manually

Operator provides:

- drink_name
- result_selector

Job writes logs to App Insights and updates PostgreSQL.

## 9.2 Rotate API key (manual, MVP)

1. Generate new key.
2. Update Key Vault secret.
3. Restart MCP app revision.
4. Update calling client configuration.

## 9.3 MCP API Key Generation (MVP)

- Local deploy script (`scripts/deploy-dev.sh`):
  - If `MCP_API_KEY` is not provided, a strong random key is auto-generated and written to Key Vault during deployment.
  - If `MCP_API_KEY` is provided, that value is used.
- GitHub deploy workflow (`.github/workflows/deploy-dev.yml`):
  - If `MCP_API_KEY` secret is set, it is used.
  - If not set, the workflow auto-generates a key for that deployment.

## 10. Delivery Checklist

## 10.1 Phase 1 (MVP)

- [ ] Provision ACR and grant pull permissions to Container Apps identities
- [ ] Add Bicep infra files for Phase 1 resources
- [ ] Add PostgreSQL migration scripts
- [ ] Implement MCP API tools and API key middleware
- [ ] Containerize MCP app and scraper job
- [ ] Deploy to rg-cocktailagent-dev-wus-01 in westus
- [ ] Validate required Owner tag on all resources
- [ ] Validate monthly spend is within target band

## 10.2 Phase 2

- [ ] Provision Azure AI Search
- [ ] Provision Azure OpenAI access for embedding generation
- [ ] Configure embedding model: text-embedding-3-small
- [ ] Configure embedding region fallback policy (secondary Azure region)
- [ ] Select and document specific secondary Azure region name for embeddings
- [ ] Use Azure AI Search Serverless Developer (Preview) in West Central US for Dev
- [ ] Implement single unified cocktails index
- [ ] Build indexing pipeline
- [ ] Implement manual reindex trigger flow
- [ ] Add hybrid MCP recommendation/search tools
- [ ] Add trigger_reindex MCP tool with authenticated access
- [ ] Build 50-prompt evaluation set
- [ ] Generate evaluation prompts from templates and complete user review
- [ ] Enforce category quotas: 15 ingredient, 15 flavor, 10 strength/sweetness, 10 situational
- [ ] Run relevance/latency evaluation
- [ ] Validate thresholds: top-3 relevance >= 70%, p95 latency <= 2.5s

## 10.3 Phase 3

- [ ] Provision Service Bus
- [ ] Add scrape_requests schema and tooling
- [ ] Implement ensure_cocktail_available and get_scrape_status
- [ ] Implement queue worker retry and DLQ handling

## 11. Immediate Next Decisions Required

- None (Phase 2 secondary region confirmed as East US)

## 12. Budget Control Notes

- Phase 1 budget target: <= $50/month ✅ **Achieved (~$40-45/month)**
- Phase 2 introduces Azure AI Search + Azure OpenAI with usage-based billing assumptions
- **Phase 2 Cost Estimate** (documented in [PHASE2_COST_ESTIMATE.md](PHASE2_COST_ESTIMATE.md)):
  - Azure AI Search (Serverless Developer Preview, West Central US): no billed compute/storage during current preview period (estimated usage visible in telemetry)
  - Azure OpenAI (text-embedding-3-small): $0.01/month (negligible)
  - **Phase 2 Total (current preview billing period)**: approximately $0.01/month billed
- **Combined Phase 1 + Phase 2 Total (current preview billing period)**: approximately $40-45/month
- **Phase 2 Authorization**: ✅ **Approved to proceed with Phase 2 as planned**
  - Rationale: Phase 2 provides meaningful semantic search capabilities with a usage-based development path
  - Monitoring: Track actual costs post-deployment against estimate
  - Risk note: Serverless Developer is preview-only, has limited regions, and billing terms can change with notice
  - Phase 3 (Service Bus): Expected minimal additional cost (~$1-5/month)

## 13. Phase 1 Gaps (Post-Deployment Review)

The following items were identified as still missing or partially complete after deployment verification.

### 13.1 Security and API Contract

- [x] Enforce API key middleware on MCP tool endpoints (`/tools/*`).
- [x] Implement missing Phase 1 MCP tools:
  - [x] `recommend_cocktails(preferences, limit)`
- [ ] Defer `get_similar_cocktails(name_or_id)` to post-Phase 1 scope.

### 13.2 Data and Migrations

- [x] Add explicit PostgreSQL migration script(s) and run them in CI/CD deploy flow.
  - Migration runner: `scraper/migration_runner.py`
  - CLI tool: `python -m scraper.cli migrate`
  - Migrations stored in: `scraper/migrations/M###_*.sql`
  - Initial schema (M001) covers pages and recipe_sections tables.
  - GitHub Actions workflow integration: runs after Bicep deployment.
  - Local deployment script integration: Phase 4 of deploy-dev.sh.
- [x] Keep migration process idempotent and separate from runtime app startup where practical.
  - `migrations_applied` table tracks which migrations have run.
  - All migrations use `IF NOT EXISTS` for safety.
  - Can be run standalone via CLI or as part of CI/CD.

### 13.3 Observability

- [x] Add baseline alert rules in Azure (for example: API availability, 5xx/error rate, and scraper job failures).
  - `alert-api-replicas-low-dev` (Replicas < 1)
  - `alert-api-5xx-dev` (Requests where statusCodeCategory=5XX)
  - `alert-scraper-job-failures-dev` (Executions where state=Failed)
- [x] Add/update App Insights dashboard/workbook for Phase 1 operational visibility.
  - Workbook ID: `c040e4c9-b9b6-46a3-96f8-591e1797ef2d`
  - Display name: "Phase 1 - Cocktail Agent Observability"
  - Resource type: `microsoft.insights/workbooks`
  - Linked to App Insights: `ai-cocktailagent-dev-wus-01`
  - Displays alert configuration and key operational metrics

### 13.4 Governance and Cost Validation

- [ ] Resolve missing Owner tag on auto-created resources where supported, or document policy exemption.
- [ ] Run and record budget validation against Phase 1 target (`<= $50/month`).
