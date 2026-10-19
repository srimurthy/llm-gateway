output "vpc_id" {
  description = "VPC ID."
  value       = module.network.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnets."
  value       = module.network.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnets."
  value       = module.network.public_subnet_ids
}

output "nat_public_ips" {
  description = "Egress IPs allowed by Azure OpenAI."
  value       = module.network.nat_public_ips
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS private endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "EKS cluster CA."
  value       = module.eks.cluster_certificate_authority_data
}

output "node_security_group_id" {
  description = "Node security group."
  value       = module.eks.node_security_group_id
}

output "karpenter_queue_name" {
  description = "Karpenter interruption queue."
  value       = module.eks.karpenter_queue_name
}

output "karpenter_node_role_name" {
  description = "Karpenter node role, for deploy/karpenter EC2NodeClass."
  value       = module.eks.karpenter_node_role_name
}

output "valkey_endpoint" {
  description = "Valkey configuration endpoint, for Helm values."
  value       = "${module.valkey.configuration_endpoint}:${module.valkey.port}"
}

output "valkey_auth_secret_arn" {
  description = "Valkey AUTH secret, synced into the cluster by External Secrets."
  value       = module.valkey.auth_secret_arn
}

output "jobs_queue_url" {
  description = "Async job queue URL, for Helm values."
  value       = module.job_queue.queue_url
}
