variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
}

variable "region" {
  description = "AWS region of the cluster."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the cluster."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the internet-facing NLB (one per AZ)."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the internal ALB."
  type        = list(string)
}

variable "node_security_group_id" {
  description = "Node security group; the ALB reaches the Istio ingress pods through it."
  type        = string
}

variable "client_cidrs" {
  description = <<-EOT
    Public egress ranges of the corporate network. The NLB's security group admits only
    these, so the gateway is on the internet but not open to it.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.client_cidrs) > 0 && !contains(var.client_cidrs, "0.0.0.0/0")
    error_message = "client_cidrs must list specific corporate egress ranges, never 0.0.0.0/0."
  }
}

variable "certificate_arn" {
  description = "ACM certificate (in this region) for the public hostname; the ALB terminates TLS with it."
  type        = string
}

variable "enable_waf" {
  description = "Attach AWS WAF (managed rule groups) to the ALB."
  type        = bool
  default     = true
}

variable "access_logs_bucket" {
  description = "S3 bucket for NLB and ALB access logs. Null disables access logs."
  type        = string
  default     = null
}

variable "karpenter_queue_name" {
  description = "Karpenter interruption queue."
  type        = string
}

variable "external_secret_arns" {
  description = "Secrets that External Secrets may read and sync into the cluster."
  type        = list(string)
}

variable "chart_versions" {
  description = <<-EOT
    Helm chart versions. Defaults are the last versions this stack was tested with;
    upgrade deliberately, one component at a time, and Istio one minor at a time.
  EOT
  nullable    = false
  type = object({
    istio                        = string
    aws_load_balancer_controller = string
    karpenter                    = string
    external_secrets             = string
    argo_cd                      = string
  })
  default = {
    istio                        = "1.27.1"
    aws_load_balancer_controller = "1.13.0"
    karpenter                    = "1.6.0"
    external_secrets             = "0.18.0"
    argo_cd                      = "8.1.0"
  }
}

variable "enable_argo_cd" {
  description = "Install Argo CD, which deploys everything under deploy/. Disable if your platform team runs it centrally."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Protect the NLB and ALB from deletion."
  type        = bool
  default     = true
}

variable "alarm_topic_arn" {
  description = "SNS topic for the ingress health alarm. Null creates the alarm without actions."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags added to every AWS resource."
  type        = map(string)
  default     = {}
}
