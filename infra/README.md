# Infrastructure

Terraform for both AWS regions and Azure OpenAI. No Crossplane: Terraform owns cloud
resources and the cluster platform; Argo CD owns everything in `deploy/`.

## Layout

```
modules/                 Reusable building blocks, one concern each
  network/               VPC, subnets, NAT, VPC endpoints
  eks-cluster/           Private EKS, system node group, Karpenter IAM
  valkey/                ElastiCache Valkey (cluster mode, TLS, AUTH)
  job-queue/             SQS + DLQ + alarm
  gateway-iam/           Pod Identity roles (API, worker, vLLM)
  platform/              Helm: LB controller, Istio, Karpenter, External Secrets, Argo CD;
                         the edge (public NLB -> internal ALB + WAF) and its health check
  global-data/           DynamoDB global tables, multi-Region KMS key, replicated secrets
  public-zone/           Public hosted zone and per-region ACM certificates
  api-dns/               Latency + failover records pointing at each public NLB
  azure-openai/          Azure OpenAI accounts and deployments
  stacks/                Compositions applied once per region
    region-foundation/   network + eks-cluster + valkey + job-queue + gateway-iam
    region-platform/     platform
live/prod/               Thin roots: backend, providers, inputs. One state each.
```

## State and apply order

Each root has its own state in S3 (native S3 locking, `use_lockfile = true`), so a
failed apply stays small and every plan is quick. Roots read each other's outputs through
`terraform_remote_state`.

| # | Root | Needs | Why separate |
|---|---|---|---|
| 1 | `live/prod/global` | – | Shared by both regions; delegate the zone (output `name_servers`) before the certificates can validate |
| 2 | `live/prod/us-east-1/foundation`, `live/prod/us-west-2/foundation` | 1 | Per-region failure domain |
| 3 | `live/prod/us-east-1/platform`, `live/prod/us-west-2/platform` | 2 | Helm needs a running cluster to plan |
| 4 | `live/prod/azure` | 2 (NAT IPs) | Different cloud and credentials |
| 5 | `live/prod/dns` | 2, 3 | Needs both regions' NLBs |

```sh
cd infra/live/prod/global
terraform init -backend-config="bucket=<state-bucket>"
terraform plan -out tfplan && terraform apply tfplan
```

The EKS API endpoint is private. Run the `platform` roots from a runner inside the
corporate network, listed in `api_allowed_cidrs`.

## Before the first apply

- **State bucket:** create it with versioning, SSE-KMS, block-public-access and a bucket
  policy limited to the CI and admin roles. State contains the Valkey AUTH token.
- **Placeholders:** replace the values in every `terraform.tfvars` (account ID, CIDRs,
  admin roles, Azure subscription).
- **Model weights bucket:** mirror the weights to S3 (`model_bucket_arn`).
- **Lock files:** run `make tf-lock` and commit the `.terraform.lock.hcl` files, so every
  platform gets the same verified provider builds.

## Conventions

- Pin module versions with `~>` and provider ranges in modules. Roots pin providers
  with `~>`.
- Every variable and output has a description. tflint enforces it.
- Default tags (`Project`, `Environment`, `ManagedBy`) are set once on the provider.
- No secrets in variables or outputs. Provider keys are written out of band
  (`scripts/sync-azure-keys.sh`).
- Least privilege: Bedrock access is limited to listed model ARNs (wildcards are rejected
  by validation), and each workload has its own Pod Identity role.

## Chart and add-on versions

`modules/platform/variables.tf` holds the tested Helm chart versions. Upgrade one
component at a time, and Istio one minor version at a time. EKS add-ons track
`most_recent` for the cluster's Kubernetes version, so they move only when
`kubernetes_version` does.
