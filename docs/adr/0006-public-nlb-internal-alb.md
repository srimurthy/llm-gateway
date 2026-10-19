# 0006. Public NLB in front of an internal ALB

**Status:** accepted (supersedes the private-only edge)

## Context

Callers are on the corporate network, but there is no private network path (Transit
Gateway, VPN) from it to the gateway VPCs. The edge must therefore be reachable over the
internet while staying closed to everyone except the company.

## Decision

- **Public NLB** in the public subnets, with one Elastic IP per AZ. Its security group
  admits only the corporate egress ranges (`client_cidrs`). Validation rejects
  `0.0.0.0/0`.
- **Internal ALB** in the private subnets, registered as the NLB's target. It terminates
  TLS with an ACM certificate, applies AWS WAF, and re-encrypts to the Istio ingress
  gateway.
- **Public Route 53 zone** with latency records per region, each guarded by the existing
  alarm-backed health check.

## Why both load balancers

- **The NLB** gives static IPs (for corporate firewall allowlists) and a security group on
  real client IPs.
- **The ALB** gives ACM certificates, WAF, HTTP-level hygiene (`drop_invalid_header_fields`,
  desync mitigation) and least-outstanding-requests balancing for long streams.
- **Neither alone does both.** A single public ALB would have no static IPs.

## Consequences

- **Exposure:** the service is internet-facing, but the network edge allows only corporate
  egress IPs, and Istio still requires a corporate JWT. Two independent controls must
  both fail before anyone else gets in.
- **IP changes:** corporate egress IPs must be kept current in `client_cidrs`. A new
  office or proxy egress IP that is not listed is refused at the NLB.
- **TLS:** traffic decrypts once, inside the private subnets, to run WAF, and is
  re-encrypted to the mesh.
- **Health checks:** Route 53 endpoint health checks would have to come from the internet,
  so the security group would need to admit them. The CloudWatch-alarm health check
  avoids that.
- **Cost:** two load balancers per region, plus WAF requests.
