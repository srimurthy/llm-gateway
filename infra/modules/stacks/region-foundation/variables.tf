variable "name" {
  description = "Regional name prefix, for example llmgw-prod-use1. Also the EKS cluster name."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC /16 for this region. Must not overlap the other region or corporate ranges."
  type        = string
}

variable "api_allowed_cidrs" {
  description = "Networks allowed to reach the private Kubernetes API (CI runners, operators)."
  type        = list(string)
}

variable "admin_role_arns" {
  description = "IAM roles with cluster-admin access."
  type        = list(string)
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.33"
}

variable "valkey_node_type" {
  description = "Valkey node type."
  type        = string
  default     = "cache.r7g.large"
}

variable "bedrock_resource_arns" {
  description = "Bedrock models and inference profiles the gateway may invoke."
  type        = list(string)
}

variable "table_names" {
  description = "Global table names from the global stack."
  type = object({
    tenants = string
    usage   = string
    jobs    = string
  })
}

variable "kms_key_arn" {
  description = "This region's copy of the shared data key."
  type        = string
}

variable "provider_secret_arns" {
  description = "This region's replicas of the provider API key secrets."
  type        = list(string)
}

variable "model_bucket_arn" {
  description = "S3 bucket with mirrored SLM weights."
  type        = string
  default     = null
}

variable "alarm_topic_arn" {
  description = "SNS topic for operational alarms."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
