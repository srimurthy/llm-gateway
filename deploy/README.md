# Cluster contents

Everything inside the EKS clusters, applied by Argo CD. Terraform installs the
controllers these resources need (Istio, Karpenter, External Secrets, the AWS Load
Balancer Controller) in `infra/modules/platform`.

| Path | Contents | Region-specific? |
|---|---|---|
| `charts/llm-gateway/` | API and worker Deployments, HPA, PDBs, VirtualService, DestinationRule, mTLS and AuthorizationPolicies, routing ConfigMap | `values-<region>.yaml` |
| `istio/` | Ingress Gateway and TLS, JWT authentication, L1 and L2 rate-limit EnvoyFilters, egress for Azure and AWS APIs | no |
| `ratelimit/` | Envoy ratelimit service (L2 decisions) and its rules | overlays |
| `platform/` | ClusterSecretStore, Karpenter node classes and pools | overlays |
| `slm/` | vLLM serving the self-hosted model on GPU nodes | no |
| `argocd/<region>/` | The Applications for each cluster, ordered by sync wave | yes |

## Bootstrap

Once per cluster, after the Terraform `platform` stack:

```sh
aws eks update-kubeconfig --name llmgw-prod-use1 --region us-east-1
kubectl apply -f deploy/argocd/us-east-1/
```

After that, Git is the source of truth: CI opens a pull request that pins each new image
digest, and Argo CD syncs whatever merges.

## Values that come from Terraform

Region files hold values from `terraform output -json foundation` in
`infra/live/prod/<region>/foundation`:

| Value | Output |
|---|---|
| `valkey.endpoint` | `valkey_endpoint` |
| `valkey.authSecretId` | name in `valkey_auth_secret_arn` |
| `jobsQueueUrl` | `jobs_queue_url` |
| Karpenter `role` | `karpenter_node_role_name` |

## Changing limits

- **Requests per minute (L2):** edit `ratelimit/base/config.yaml`.
- **Tokens per minute (L3):** run `scripts/put-tenant-policy.sh`. It takes effect within
  60 seconds, with no deploy.
- **Per-pod burst (L1):** edit `istio/ratelimit-local.yaml`.

## Security model

- **Edge:** traffic arrives from corporate egress IPs through the public NLB and the
  internal ALB (TLS, WAF). Only the ingress gateway accepts it into the mesh, and it
  requires a valid corporate JWT with a `tenant` claim.
- **mTLS:** STRICT on every workload. Each workload accepts only the identities that need
  to call it (AuthorizationPolicy).
- **Egress:** the mesh runs `REGISTRY_ONLY`. The only external destinations are AWS APIs
  (through VPC endpoints) and the two Azure OpenAI hosts (through the egress gateway).
- **Pods:** run as non-root with a read-only root filesystem, all capabilities dropped and
  `RuntimeDefault` seccomp. Service account tokens are not mounted.
