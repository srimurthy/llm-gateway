variable "state_bucket" {
  description = "S3 bucket holding the Terraform state of the other stacks."
  type        = string
}

variable "client_cidrs" {
  description = "Corporate public egress ranges allowed through the NLB."
  type        = list(string)
}

variable "access_logs_bucket" {
  description = "S3 bucket for load balancer access logs. Null disables them."
  type        = string
  default     = null
}

variable "alarm_topic_arn" {
  description = "SNS topic for alarms."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to every resource through the provider's default_tags."
  type        = map(string)
  default     = {}
}
