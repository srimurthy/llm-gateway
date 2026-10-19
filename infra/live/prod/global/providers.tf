provider "aws" {
  alias  = "primary"
  region = var.primary_region

  default_tags {
    tags = merge(var.tags, {
      Project     = "llm-gateway"
      Environment = "prod"
      ManagedBy   = "terraform"
    })
  }
}

provider "aws" {
  alias  = "secondary"
  region = var.secondary_region

  default_tags {
    tags = merge(var.tags, {
      Project     = "llm-gateway"
      Environment = "prod"
      ManagedBy   = "terraform"
    })
  }
}
