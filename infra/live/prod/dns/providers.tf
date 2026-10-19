provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = merge(var.tags, {
      Project     = "llm-gateway"
      Environment = "prod"
      ManagedBy   = "terraform"
    })
  }
}
