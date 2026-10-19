variable "name" {
  description = "Replication group ID and name prefix."
  type        = string
}

variable "vpc_id" {
  description = "VPC for the security group."
  type        = string
}

variable "subnet_group_name" {
  description = "ElastiCache subnet group spanning three AZs."
  type        = string
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to connect on 6379 (EKS nodes)."
  type        = list(string)
}

variable "node_type" {
  description = "Cache node type."
  type        = string
  default     = "cache.r7g.large"
}

variable "shards" {
  description = "Number of shards (cluster mode)."
  type        = number
  default     = 2
}

variable "replicas_per_shard" {
  description = "Replicas per shard. At least 1 for Multi-AZ failover."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas_per_shard >= 1
    error_message = "replicas_per_shard must be at least 1 for automatic failover."
  }
}

variable "kms_key_arn" {
  description = "KMS key for encryption at rest and for the auth secret. Null uses AWS-managed keys."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
