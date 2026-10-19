data "terraform_remote_state" "global" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/global.tfstate"
    region = "us-east-1"
  }
}

data "terraform_remote_state" "platform_use1" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/us-east-1/platform.tfstate"
    region = "us-east-1"
  }
}

data "terraform_remote_state" "platform_usw2" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/us-west-2/platform.tfstate"
    region = "us-east-1"
  }
}

locals {
  platforms = {
    "us-east-1" = data.terraform_remote_state.platform_use1.outputs.platform
    "us-west-2" = data.terraform_remote_state.platform_usw2.outputs.platform
  }
}

module "api_dns" {
  source = "../../../modules/api-dns"

  zone_id     = data.terraform_remote_state.global.outputs.zone_id
  record_name = var.record_name

  regional_endpoints = {
    for region, platform in local.platforms : region => {
      dns_name        = platform.public_nlb_dns_name
      zone_id         = platform.public_nlb_zone_id
      health_check_id = platform.ingress_health_check_id
    }
  }
}
