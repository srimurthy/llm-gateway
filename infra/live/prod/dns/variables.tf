variable "state_bucket" {
  description = "S3 bucket holding the Terraform state of the other stacks."
  type        = string
}

variable "record_name" {
  description = "Hostname clients call (must match the certificate in the global stack)."
  type        = string
  default     = "api.llm.acme.com"
}

variable "tags" {
  description = "Tags applied to every resource through the provider's default_tags."
  type        = map(string)
  default     = {}
}
