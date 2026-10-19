variable "name_prefix" {
  description = "Prefix for account names and custom subdomains (globally unique)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group to create."
  type        = string
}

variable "locations" {
  description = "Azure regions, one account per region. The first also hosts the resource group."
  type        = list(string)

  validation {
    condition     = length(var.locations) >= 2
    error_message = "Use at least two regions so one Azure outage does not remove the provider."
  }
}

variable "allowed_ip_ranges" {
  description = "Only these public IPs (the AWS NAT gateways) may call the accounts."
  type        = list(string)
}

variable "deployments" {
  description = "Model deployments created in every region, keyed by deployment name."
  type = map(object({
    model_name    = string
    model_version = string
    sku_name      = string
    capacity      = number
  }))
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
