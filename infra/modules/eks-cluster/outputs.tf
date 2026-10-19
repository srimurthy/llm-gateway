output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Private API endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 cluster CA."
  value       = module.eks.cluster_certificate_authority_data
}

output "node_security_group_id" {
  description = "Security group shared by all nodes (and pods, which use node networking)."
  value       = module.eks.node_security_group_id
}

output "karpenter_queue_name" {
  description = "SQS queue Karpenter reads for spot interruption and rebalance events."
  value       = module.karpenter.queue_name
}

output "karpenter_node_role_name" {
  description = "IAM role for Karpenter-launched nodes, referenced by EC2NodeClass."
  value       = module.karpenter.node_iam_role_name
}
