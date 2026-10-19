variable "state_bucket" {
  description = "S3 bucket holding the Terraform state of the other stacks."
  type        = string
}

variable "name" {
  description = "Regional name prefix and EKS cluster name."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC /16."
  type        = string
}

variable "api_allowed_cidrs" {
  description = "Networks allowed to reach the Kubernetes API."
  type        = list(string)
}

variable "admin_role_arns" {
  description = "IAM roles with cluster-admin access."
  type        = list(string)
}

variable "bedrock_resource_arns" {
  description = "Bedrock models and inference profiles the gateway may invoke."
  type        = list(string)
}

variable "model_bucket_arn" {
  description = "S3 bucket with mirrored SLM weights."
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
