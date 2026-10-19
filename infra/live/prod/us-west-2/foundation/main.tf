data "terraform_remote_state" "global" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/global.tfstate"
    region = "us-east-1"
  }
}

locals {
  global = data.terraform_remote_state.global.outputs
}

module "foundation" {
  source = "../../../../modules/stacks/region-foundation"

  name                  = var.name
  vpc_cidr              = var.vpc_cidr
  api_allowed_cidrs     = var.api_allowed_cidrs
  admin_role_arns       = var.admin_role_arns
  bedrock_resource_arns = var.bedrock_resource_arns
  model_bucket_arn      = var.model_bucket_arn
  alarm_topic_arn       = var.alarm_topic_arn

  table_names          = local.global.table_names
  kms_key_arn          = local.global.kms_key_arns.secondary
  provider_secret_arns = local.global.provider_secret_arns.secondary
}
