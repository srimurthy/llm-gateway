variable "state_bucket" {
  description = "S3 bucket holding the Terraform state of the other stacks."
  type        = string
}

variable "subscription_id" {
  description = "Azure subscription for the OpenAI accounts."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for account names and custom subdomains (globally unique)."
  type        = string
}

variable "locations" {
  description = "Azure regions."
  type        = list(string)
}

variable "deployments" {
  description = "Model deployments per region."
  type = map(object({
    model_name    = string
    model_version = string
    sku_name      = string
    capacity      = number
  }))
}

variable "tags" {
  description = "Tags applied to every resource through the provider's default_tags."
  type        = map(string)
  default     = {}
}
