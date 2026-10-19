variable "region" {
  description = "AWS region."
  type        = string
}

variable "foundation" {
  description = "Outputs of this region's foundation stack."
  type = object({
    cluster_name           = string
    vpc_id                 = string
    public_subnet_ids      = list(string)
    private_subnet_ids     = list(string)
    node_security_group_id = string
    karpenter_queue_name   = string
    valkey_auth_secret_arn = string
  })
}

variable "client_cidrs" {
  description = "Corporate public egress ranges allowed through the NLB."
  type        = list(string)
}

variable "certificate_arn" {
  description = "ACM certificate in this region for the public hostname."
  type        = string
}

variable "access_logs_bucket" {
  description = "S3 bucket for load balancer access logs. Null disables them."
  type        = string
  default     = null
}

variable "ingress_tls_secret_arn" {
  description = "This region's replica of the ingress TLS secret."
  type        = string
}

variable "chart_versions" {
  description = "Override platform chart versions. Null keeps the module defaults."
  type = object({
    istio                        = string
    aws_load_balancer_controller = string
    karpenter                    = string
    external_secrets             = string
    argo_cd                      = string
  })
  default = null
}

variable "alarm_topic_arn" {
  description = "SNS topic for operational alarms."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags added to every AWS resource."
  type        = map(string)
  default     = {}
}
