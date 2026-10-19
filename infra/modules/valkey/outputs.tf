output "configuration_endpoint" {
  description = "Cluster-mode configuration endpoint (host only)."
  value       = aws_elasticache_replication_group.this.configuration_endpoint_address
}

output "port" {
  description = "Valkey port."
  value       = aws_elasticache_replication_group.this.port
}

output "auth_secret_arn" {
  description = "Secrets Manager secret holding the AUTH token (synced into Kubernetes by External Secrets)."
  value       = aws_secretsmanager_secret.auth.arn
}
