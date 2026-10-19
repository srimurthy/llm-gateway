module "public_zone" {
  source = "../../../modules/public-zone"

  providers = {
    aws.primary   = aws.primary
    aws.secondary = aws.secondary
  }

  zone_name    = var.zone_name
  api_hostname = var.api_hostname
}

module "global_data" {
  source = "../../../modules/global-data"

  providers = {
    aws.primary   = aws.primary
    aws.secondary = aws.secondary
  }

  name_prefix           = var.name_prefix
  secondary_region      = var.secondary_region
  provider_secret_names = var.provider_secret_names
}
