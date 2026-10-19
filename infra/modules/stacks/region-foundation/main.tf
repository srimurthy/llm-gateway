/**
 * Everything one region needs below Kubernetes: network, cluster, Valkey, the job queue
 * and the gateway's IAM roles. Applied once per region with region-specific inputs.
 */

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  table_arns = {
    for key, name in var.table_names :
    key => "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${name}"
  }
}

module "network" {
  source = "../../network"

  name         = var.name
  cidr         = var.vpc_cidr
  cluster_name = var.name
  tags         = var.tags
}

module "eks" {
  source = "../../eks-cluster"

  cluster_name             = var.name
  kubernetes_version       = var.kubernetes_version
  vpc_id                   = module.network.vpc_id
  private_subnet_ids       = module.network.private_subnet_ids
  control_plane_subnet_ids = module.network.intra_subnet_ids
  api_allowed_cidrs        = var.api_allowed_cidrs
  admin_role_arns          = var.admin_role_arns
  tags                     = var.tags
}

module "valkey" {
  source = "../../valkey"

  name                       = var.name
  vpc_id                     = module.network.vpc_id
  subnet_group_name          = module.network.elasticache_subnet_group_name
  allowed_security_group_ids = [module.eks.node_security_group_id]
  node_type                  = var.valkey_node_type
  kms_key_arn                = var.kms_key_arn
  tags                       = var.tags
}

module "job_queue" {
  source = "../../job-queue"

  name            = "${var.name}-jobs"
  alarm_topic_arn = var.alarm_topic_arn
  tags            = var.tags
}

module "gateway_iam" {
  source = "../../gateway-iam"

  name                  = var.name
  cluster_name          = module.eks.cluster_name
  bedrock_resource_arns = var.bedrock_resource_arns
  table_arns            = local.table_arns
  queue_arn             = module.job_queue.queue_arn
  provider_secret_arns  = var.provider_secret_arns
  model_bucket_arn      = var.model_bucket_arn
  kms_key_arns          = [var.kms_key_arn]
  tags                  = var.tags
}
