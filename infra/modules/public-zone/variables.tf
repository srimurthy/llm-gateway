variable "zone_name" {
  description = "Public hosted zone to create, for example llm.acme.com. Delegate it from the parent domain with the name_servers output."
  type        = string
}

variable "api_hostname" {
  description = "Hostname clients call, inside zone_name. Each region's ALB gets an ACM certificate for it."
  type        = string

  validation {
    condition     = endswith(var.api_hostname, ".${var.zone_name}")
    error_message = "api_hostname must be inside zone_name."
  }
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
