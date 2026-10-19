# 0005. Terraform in layered states; Argo CD inside the clusters

**Status:** accepted

## Context

Crossplane is ruled out. The infrastructure spans two AWS regions, a global layer and
Azure. The Helm and Kubernetes providers need a running cluster at plan time.

## Decision

- **Terraform owns:**
  - cloud resources;
  - the cluster platform (controllers whose CRDs everything else needs);
  - the edge load balancers (public NLB, internal ALB) and WAF.
- **Argo CD owns:** everything in `deploy/`.
- **States:** separate per layer and per region (`global`, `<region>/foundation`,
  `<region>/platform`, `dns`, `azure`). Thin roots in `live/` compose modules through
  per-region stacks.
- **Load balancer ownership:** Terraform creates the NLB and the ALB, and binds the ALB to
  the Istio pods with a TargetGroupBinding, so their ARNs are stable for alarms and DNS.

## Consequences

- **Blast radius:** an apply touches one region and one layer at a time, and plans stay
  fast.
- **Coupling:** cross-layer references go through `terraform_remote_state`, which couples
  roots to each other's output names. Keep those outputs stable.
- **Ordering:** the apply order is explicit in `infra/README.md`. CI plans every root on
  pull requests.
