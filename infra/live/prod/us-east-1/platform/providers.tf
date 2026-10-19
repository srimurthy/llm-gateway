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

# The API endpoint is private: run this stack from a runner inside the corporate network.
provider "helm" {
  kubernetes = {
    host                   = local.foundation.cluster_endpoint
    cluster_ca_certificate = base64decode(local.foundation.cluster_certificate_authority_data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.foundation.cluster_name, "--region", "us-east-1"]
    }
  }
}
