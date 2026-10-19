variable "name_prefix" {
  description = "Prefix for tables, keys and secrets."
  type        = string
}

variable "secondary_region" {
  description = "Region that holds the replicas (the aws.secondary provider's region)."
  type        = string
}

variable "provider_secret_names" {
  description = <<-EOT
    Secrets for provider API keys, keyed by a short name (for example
    azure-openai/eastus2). Terraform creates the secret and its replica; the value is
    written out of band by scripts/sync-azure-keys.sh so keys never enter state.
  EOT
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
