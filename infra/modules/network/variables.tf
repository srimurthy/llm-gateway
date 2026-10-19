variable "name" {
  description = "Name prefix for every resource in this VPC."
  type        = string
}

variable "cidr" {
  description = "VPC CIDR. Must be a /16: subnets are carved from it at fixed offsets."
  type        = string

  validation {
    condition     = can(cidrhost(var.cidr, 0)) && endswith(var.cidr, "/16")
    error_message = "cidr must be a valid IPv4 /16, for example 10.40.0.0/16."
  }
}

variable "cluster_name" {
  description = "EKS cluster name, used for subnet discovery tags."
  type        = string
}

variable "flow_log_retention_days" {
  description = "Retention for VPC flow logs."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
