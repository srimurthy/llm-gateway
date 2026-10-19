variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes minor version. Upgrade one minor at a time."
  type        = string
  default     = "1.33"
}

variable "vpc_id" {
  description = "VPC for the cluster."
  type        = string
}

variable "private_subnet_ids" {
  description = "Subnets for nodes and pods."
  type        = list(string)
}

variable "control_plane_subnet_ids" {
  description = "Subnets for the control-plane ENIs."
  type        = list(string)
}

variable "api_allowed_cidrs" {
  description = "Networks allowed to reach the private API endpoint (CI runners, operators)."
  type        = list(string)
}

variable "admin_role_arns" {
  description = "IAM roles granted cluster-admin through EKS access entries."
  type        = list(string)
}

variable "system_instance_types" {
  description = "Instance types for the managed node group that runs cluster add-ons."
  type        = list(string)
  default     = ["m7i.large", "m6i.large"]
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
