# Phase 2 Cost Estimate: Azure AI Search + Azure OpenAI

## Estimation Date
June 22, 2026

## Services in Scope

### 1. Azure AI Search
- **Pricing model**: Serverless Developer (Preview)
- **Region**: West Central US
- **Pricing**: Usage-based (Compute Units + indexed storage); current preview billing is not yet enabled

### 2. Azure OpenAI (Embeddings)
- **Model**: text-embedding-3-small
- **Primary**: West US
- **Secondary**: East US (fallback only, minimal usage expected)
- **Pricing**: Embeddings are priced per 1K tokens

## Cost Breakdown Assumptions

### Phase 2 Workload Profile (Dev)
- **Evaluation dataset**: 50 prompts (one-time embedding)
- **Ongoing cocktail database**: ~300 recipes at ~500 tokens each = 150K tokens
- **Index reindex frequency**: Monthly (manual trigger only)
- **Query volume**: ~100 queries/month during development/testing

### Azure AI Search - Serverless Developer (Preview)
- **Compute billing**: consumption-based when active (no billed compute while idle)
- **Storage billing**: per indexed GB/month once billing is enabled
- **Current preview billing status**: billed charges not yet enabled; estimated usage appears in telemetry only
- **Subtotal (currently billed)**: $0/month

### Azure OpenAI - text-embedding-3-small
- **Input pricing**: $0.02 per 1M tokens
- **Output pricing**: $0.02 per 1M tokens (embeddings typically ~500 tokens per cocktail)

**Monthly embedding costs (West US primary, East US fallback):**
- Initial indexing (50 prompts + 300 recipes): ~200K tokens = $0.004
- Monthly reindex/updates: ~200K tokens = $0.004
- Query-time contextual embeddings (100 queries × ~200 tokens): ~20K tokens = $0.0004
- **Subtotal**: ~$0.01/month (negligible for Phase 2)

## Estimated Phase 2 Monthly Cost

| Component | Cost |
|-----------|------|
| Azure AI Search (Serverless Developer Preview - West Central US) | $0.00 (currently billed) |
| Azure OpenAI (text-embedding-3-small) | $0.01 |
| **Total Phase 2 Monthly (Dev, current preview billing period)** | **$0.01** |

## Combined Phase 1 + Phase 2 Cost

- Phase 1 baseline (Container Apps, PostgreSQL, App Insights): ~$40-45/month
- Phase 2 additions (AI Search + OpenAI): ~$0.01/month currently billed
- **Phase 1 + Phase 2 Total (current preview billing period)**: **~$40-45/month**

## Budget Impact

- Original Phase 1 target: ≤ $50/month ✅ (actual ~$40-45)
- Phase 2 target: ≤ $50/month (Phase 2 alone) ✅ **Meets target during current preview billing period**
- Combined Phase 1 + Phase 2: ~$40-45/month currently billed
- Future-state note: cost will increase when Serverless billing is enabled; monitor telemetry and recalculate before GA

## Options to Optimize Phase 2 Costs

1. **Use Serverless Developer Preview in West Central US**
   - **Recommended** for low-cost dev experimentation

2. **Use telemetry-based cost profiling**
   - Measure `x-ms-request-charge` from representative indexing and query calls
   - Extrapolate future billed cost before preview billing is enabled

3. **Keep index lean**
   - Store only fields required for retrieval/ranking
   - Reduces future storage and query compute costs

## Recommendation

**Proceed with Phase 2 as planned.** 

Rationale:
- Azure AI Search Serverless Developer is the most cost-efficient Dev path
- Embedding costs are negligible
- Combined current billed cost remains within existing budget
- Phase 2 features provide meaningful value (semantic search, hybrid recommendations)
- Add a checkpoint to re-baseline budget once Serverless billing is enabled

## Next Steps

1. ✅ Adopt Serverless Developer Preview in West Central US for Phase 2 AI Search
2. Proceed with Phase 2 deployment (Bicep templates for AI Search + OpenAI)
3. Capture telemetry-based CU and storage usage during development
4. Recalculate forecast once Microsoft enables Serverless billing

