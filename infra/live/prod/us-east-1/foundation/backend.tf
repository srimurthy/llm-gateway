# Partial configuration: pass the bucket at init time, for example
#   terraform init -backend-config="bucket=<state-bucket>"
terraform {
  backend "s3" {
    key          = "prod/us-east-1/foundation.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
