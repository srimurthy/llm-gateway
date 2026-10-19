provider "aws" {
  region = "us-west-2"

  default_tags {
    tags = merge(var.tags, {
      Project     = "llm-gateway"
      Environment = "prod"
      ManagedBy   = "terraform"
    })
  }
}
