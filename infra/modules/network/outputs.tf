output "vpc_id" {
  description = "VPC ID."
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "VPC CIDR."
  value       = module.vpc.vpc_cidr_block
}

output "private_subnet_ids" {
  description = "Private subnets for nodes, pods and the internal ALB."
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "Public subnets for NAT gateways and the public NLB."
  value       = module.vpc.public_subnets
}

output "intra_subnet_ids" {
  description = "Intra subnets for the EKS control plane."
  value       = module.vpc.intra_subnets
}

output "elasticache_subnet_group_name" {
  description = "Subnet group for Valkey."
  value       = module.vpc.elasticache_subnet_group_name
}

output "nat_public_ips" {
  description = "NAT gateway public IPs. Azure OpenAI allows only these."
  value       = module.vpc.nat_public_ips
}
