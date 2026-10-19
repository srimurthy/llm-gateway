data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/us-west-2/foundation.tfstate"
    region = "us-east-1"
  }
}

data "terraform_remote_state" "global" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "prod/global.tfstate"
    region = "us-east-1"
  }
}

locals {
  foundation = data.terraform_remote_state.foundation.outputs.foundation
}

module "platform" {
  source = "../../../../modules/stacks/region-platform"

  region                 = "us-west-2"
  foundation             = local.foundation
  client_cidrs           = var.client_cidrs
  certificate_arn        = data.terraform_remote_state.global.outputs.certificate_arns.secondary
  access_logs_bucket     = var.access_logs_bucket
  ingress_tls_secret_arn = data.terraform_remote_state.global.outputs.ingress_tls_secret_arns.secondary
  alarm_topic_arn        = var.alarm_topic_arn
}
