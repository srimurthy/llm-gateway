variable "name_prefix" {
  description = "Prefix for shared resources."
  type        = string
  default     = "llmgw-prod"
}

variable "primary_region" {
  description = "Region of the primary table and key copies."
  type        = string
  default     = "us-east-1"
}

variable "secondary_region" {
  description = "Region of the replicas."
  type        = string
  default     = "us-west-2"
}

variable "zone_name" {
  description = "Public hosted zone for the gateway."
  type        = string
  default     = "llm.acme.com"
}

variable "api_hostname" {
  description = "Hostname clients call."
  type        = string
  default     = "api.llm.acme.com"
}

variable "provider_secret_names" {
  description = "Provider API key secrets to create (values are written out of band)."
  type        = set(string)
}

variable "tags" {
  description = "Tags applied to every resource through the provider's default_tags."
  type        = map(string)
  default     = {}
}
