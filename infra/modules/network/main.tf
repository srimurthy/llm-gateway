/**
 * VPC across three AZs.
 *
 * - private /19s: nodes, pods (VPC CNI prefix delegation), the internal ALB
 * - intra /24s: EKS control-plane ENIs
 * - public /24s: NAT gateways and the Terraform-owned public NLB. They carry no ELB
 *   discovery tag, so Kubernetes cannot place any other public load balancer here.
 * - elasticache /24s: Valkey
 *
 * AWS APIs are reached through VPC endpoints, so that traffic never uses the NAT.
 */

data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  az_count = 3
  azs      = slice(data.aws_availability_zones.available.names, 0, local.az_count)

  private_subnets     = [for i in range(local.az_count) : cidrsubnet(var.cidr, 3, i)]
  intra_subnets       = [for i in range(local.az_count) : cidrsubnet(var.cidr, 8, 240 + i)]
  public_subnets      = [for i in range(local.az_count) : cidrsubnet(var.cidr, 8, 244 + i)]
  elasticache_subnets = [for i in range(local.az_count) : cidrsubnet(var.cidr, 8, 248 + i)]

  interface_endpoints = toset([
    "bedrock-runtime",
    "ec2",
    "ecr.api",
    "ecr.dkr",
    "eks-auth",
    "elasticloadbalancing",
    "kms",
    "logs",
    "secretsmanager",
    "sqs",
    "sts",
  ])
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.21"

  name = var.name
  cidr = var.cidr
  azs  = local.azs

  private_subnets     = local.private_subnets
  intra_subnets       = local.intra_subnets
  public_subnets      = local.public_subnets
  elasticache_subnets = local.elasticache_subnets

  create_elasticache_subnet_group = true

  enable_nat_gateway     = true
  single_nat_gateway     = false
  one_nat_gateway_per_az = true

  enable_dns_hostnames = true
  enable_dns_support   = true

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
    "karpenter.sh/discovery"          = var.cluster_name
  }

  manage_default_security_group  = true
  default_security_group_ingress = []
  default_security_group_egress  = []

  enable_flow_log                                 = true
  create_flow_log_cloudwatch_log_group            = true
  create_flow_log_cloudwatch_iam_role             = true
  flow_log_max_aggregation_interval               = 60
  flow_log_cloudwatch_log_group_retention_in_days = var.flow_log_retention_days

  tags = var.tags
}

module "endpoints" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "~> 5.21"

  vpc_id = module.vpc.vpc_id

  create_security_group      = true
  security_group_name_prefix = "${var.name}-vpce-"
  security_group_description = "HTTPS from inside the VPC to interface endpoints"
  security_group_rules = {
    ingress_https = {
      description = "HTTPS from the VPC"
      cidr_blocks = [var.cidr]
    }
  }

  endpoints = merge(
    {
      for service in local.interface_endpoints : replace(service, ".", "_") => {
        service             = service
        private_dns_enabled = true
        subnet_ids          = module.vpc.private_subnets
        tags                = { Name = "${var.name}-${service}" }
      }
    },
    {
      s3 = {
        service         = "s3"
        service_type    = "Gateway"
        route_table_ids = module.vpc.private_route_table_ids
        tags            = { Name = "${var.name}-s3" }
      }
      dynamodb = {
        service         = "dynamodb"
        service_type    = "Gateway"
        route_table_ids = module.vpc.private_route_table_ids
        tags            = { Name = "${var.name}-dynamodb" }
      }
    },
  )

  tags = var.tags
}
