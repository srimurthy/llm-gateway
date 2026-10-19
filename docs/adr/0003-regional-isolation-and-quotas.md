# 0003. Independent regions; tenant budgets split by share

**Status:** accepted

## Context

Two active regions serve traffic. Rate-limit counters could be global (one store across
regions) or regional.

## Decision

Each region is self-contained: its own EKS cluster, Istio mesh (no multi-cluster mesh),
Valkey and ratelimit service. Only data that must survive a region loss is global:
DynamoDB global tables (tenant policies, usage, jobs) and replicated secrets.

Each region enforces `regionQuotaShare × tokens_per_minute` per tenant.

## Consequences

- **No cross-region calls on the request path.** A region keeps working whatever happens
  to the other one.
- **The default share is 1.0.** A tenant is latency-routed to one region, and must keep
  its full budget after a failover. The cost: a tenant whose traffic splits across both
  regions can briefly consume up to 2× its budget.
- **Stricter budgets:** set the share below 1.0 and accept a reduced budget during
  failover. Alternatively, add a rebalancer that adjusts shares every few seconds from
  the usage ledger (the ledger already records usage per region). The rebalancer is not
  built yet.
