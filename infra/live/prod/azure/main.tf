data "terraform_remote_state" "foundation_use1" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/us-east-1/foundation.tfstate"
    region = "us-east-1"
  }
}

data "terraform_remote_state" "foundation_usw2" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/us-west-2/foundation.tfstate"
    region = "us-east-1"
  }
}

locals {
  nat_ips = concat(
    data.terraform_remote_state.foundation_use1.outputs.foundation.nat_public_ips,
    data.terraform_remote_state.foundation_usw2.outputs.foundation.nat_public_ips,
  )
}

module "azure_openai" {
  source = "../../../modules/azure-openai"

  name_prefix         = var.name_prefix
  resource_group_name = "${var.name_prefix}-rg"
  locations           = var.locations
  allowed_ip_ranges   = local.nat_ips
  deployments         = var.deployments
  tags                = var.tags
}
