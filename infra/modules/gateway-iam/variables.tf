variable "name" {
  description = "Role name prefix."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster for the Pod Identity associations."
  type        = string
}

variable "namespace" {
  description = "Kubernetes namespace of the gateway."
  type        = string
  default     = "llm-gateway"
}

variable "api_service_account" {
  description = "Service account of the API pods."
  type        = string
  default     = "llm-gateway-api"
}

variable "worker_service_account" {
  description = "Service account of the job worker pods."
  type        = string
  default     = "llm-gateway-worker"
}

variable "bedrock_resource_arns" {
  description = <<-EOT
    Foundation models and inference profiles the gateway may invoke. A cross-region
    inference profile also needs the foundation model ARN in every region it routes to,
    so use arn:aws:bedrock:*::foundation-model/<id> for those.
  EOT
  type        = list(string)

  validation {
    condition = length(var.bedrock_resource_arns) > 0 && alltrue([
      for a in var.bedrock_resource_arns : startswith(a, "arn:aws:bedrock:") && !endswith(a, "/*")
    ])
    error_message = "bedrock_resource_arns must name specific models or profiles; a trailing /* (every model) is not allowed."
  }
}

variable "table_arns" {
  description = "DynamoDB table ARNs in this region."
  type = object({
    tenants = string
    usage   = string
    jobs    = string
  })
}

variable "queue_arn" {
  description = "Async job queue ARN."
  type        = string
}

variable "provider_secret_arns" {
  description = "Secrets Manager ARNs (this region's replicas) holding provider API keys."
  type        = list(string)
}

variable "kms_key_arns" {
  description = "KMS keys protecting the tables and secrets."
  type        = list(string)
}

variable "model_bucket_arn" {
  description = "S3 bucket with mirrored model weights for the self-hosted SLM. Null skips the role."
  type        = string
  default     = null
}

variable "slm_namespace" {
  description = "Namespace of the vLLM deployment."
  type        = string
  default     = "slm"
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
