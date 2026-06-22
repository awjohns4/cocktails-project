# Azure Architecture Plan: Cocktail Agent Data Platform

## Goal
Provide reliable cocktail recipe data to an AI agent that can:
- instruct users how to make cocktails
- recommend drinks based on preferences

This document captures:
- MVP architecture (Option 1)
- Phase 2 architecture (Option 2)
- Phase 3 architecture (agent-triggered scrape orchestration)

## Option 1 (MVP): Structured Retrieval on Azure

### Recommended services
- Azure Container Apps: host MCP server (read/query tools)
- Azure Container Apps Jobs: run scraper on-demand (manual trigger only in MVP)
- Azure Database for PostgreSQL Flexible Server: primary structured data store
- Azure Container Registry (ACR): container image storage
- Azure Blob Storage (optional): raw scrape snapshots and diagnostics
- Azure Key Vault: secret storage
- Managed Identity: service-to-service auth
- Application Insights + Log Analytics: monitoring and troubleshooting

### Why this is the MVP
- Lowest operational overhead for current Python stack
- Deterministic and explainable tool responses
- Easy to secure and scale incrementally on Azure
- Keeps data model simple while recommendation logic matures

### Data and tool flow
1. Scraper job discovers recipe URLs from search queries.
2. Scraper job extracts structured sections and stores data in PostgreSQL.
3. MCP server exposes read tools to the agent (for example: search, get recipe, recommendations from filters).
4. Agent calls MCP tools to answer user questions with grounded recipe data.

### Suggested MCP tools for MVP
- get_recipe(name_or_id)
- search_cocktails(filters)
- recommend_cocktails(preferences, limit)

Deferred beyond MVP:
- get_similar_cocktails(name_or_id)

### Security baseline
- Use Managed Identity for Container Apps to access PostgreSQL and Key Vault
- Keep credentials out of code and local config files
- Restrict network access where feasible
- Enable diagnostic logs and request tracing
- CI/CD auth posture: use `AZURE_CREDENTIALS` for MVP bootstrap, then migrate to OIDC federation as a security hardening step.

## Option 2 (Phase 2): Hybrid Recommendations with Azure AI Search

### Additional services
- Azure AI Search: hybrid retrieval (vector + keyword + metadata filters)
- Azure OpenAI embeddings for vector generation (text-embedding-3-small in Phase 2)

### Why add this in Phase 2
- Improves fuzzy recommendation quality:
  - "citrusy but not too sweet"
  - "something like a daiquiri but lower strength"
- Maintains deterministic structured retrieval for exact instructions and ingredient lists

### Hybrid retrieval pattern
1. Keep PostgreSQL as source of truth for structured recipe data.
2. Build search index documents from recipe sections and optional tasting/review text.
3. Query AI Search for candidate drinks using semantic intent.
4. Apply metadata filters (strength, sweet/sour, ingredients available).
5. Return top candidates and hydrate final answer from PostgreSQL details.

## Option 3 (Phase 3): Agent-Triggered On-Demand Scraping

### Objective
Allow the agent to request a scrape when a cocktail is missing from the database,
without blocking normal chat/tool latency.

### Additional services
- Azure Service Bus: durable queue for scrape requests
- Azure Container Apps Job (or worker app): async scrape execution
- PostgreSQL table for scrape request state tracking

### Why this belongs in Phase 3
- Introduces asynchronous orchestration complexity (queues, retries, DLQ)
- Requires additional idempotency, status, and operational controls
- Provides high value once the assistant sees real production miss patterns

### Request flow
1. Agent calls `ensure_cocktail_available(name)`.
2. MCP server checks PostgreSQL for existing recipe data.
3. If found, return immediately.
4. If missing, create a `scrape_request` record and enqueue request to Service Bus.
5. Scraper worker consumes request, scrapes Difford's, writes recipe data.
6. Worker updates request status (`pending`, `running`, `succeeded`, `failed`).
7. Agent checks `get_scrape_status(request_id)` and continues when complete.

### Suggested MCP tools for Phase 3
- ensure_cocktail_available(name)
- get_scrape_status(request_id)
- list_pending_scrape_requests(limit)

### Data model additions
- scrape_requests
  - request_id (UUID, PK)
  - cocktail_name
  - status
  - attempts
  - error_message
  - created_at
  - updated_at

### Reliability and safety controls
- Idempotency key: avoid duplicate in-flight requests for same cocktail
- Retry policy with max attempts
- Dead-letter queue handling and alerting
- Cooldown for repeated requests of the same cocktail
- Rate limits and domain allow-listing

## Rollout Plan

### Phase 1 checklist
- [x] Move local SQLite workflow to PostgreSQL schema
- [ ] Containerize scraper and MCP server
- [ ] Deploy scraper as Container Apps Job
- [ ] Deploy MCP server on Container Apps
- [ ] Configure Managed Identity and Key Vault
- [ ] Add Application Insights dashboards/alerts

### Phase 2 checklist
- [ ] Define Azure AI Search index schema
- [ ] Implement embedding generation pipeline
- [ ] Add hybrid query endpoint/tool to MCP server
- [ ] Add recommendation ranking evaluation set
- [ ] Tune retrieval quality and latency thresholds

### Phase 3 checklist
- [ ] Add `scrape_requests` table and status lifecycle
- [ ] Add Service Bus queue and worker wiring
- [ ] Implement `ensure_cocktail_available` MCP tool
- [ ] Implement `get_scrape_status` MCP tool
- [ ] Add idempotency and duplicate suppression logic
- [ ] Add retry + dead-letter handling and dashboards
- [ ] Add stale-data refresh policy (optional)

## Exit criteria

### MVP done when
- Agent can reliably fetch recipes and instructions from MCP tools
- Scraper refresh runs are automated and observable
- Production secrets and auth are managed through Azure services

### Phase 2 done when
- Recommendation relevance improves on fuzzy user queries
- Structured recipe responses remain stable and deterministic
- Latency and cost are acceptable for target usage

### Phase 3 done when
- Agent can request missing cocktails without blocking conversation latency
- On-demand scrape requests are observable and recoverable (retries/DLQ)
- Duplicate requests are suppressed and throughput remains stable
- Newly scraped cocktails become available through existing MCP read tools
