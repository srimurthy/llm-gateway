output "table_names" {
  description = "DynamoDB table names (identical in both regions)."
  value       = { for key, table in aws_dynamodb_table.this : key => table.name }
}

output "kms_key_arns" {
  description = "KMS key ARN per region."
  value = {
    primary   = aws_kms_key.data.arn
    secondary = aws_kms_replica_key.data.arn
  }
}

output "provider_secret_ids" {
  description = "Secret IDs (names) to put in the routing file's api_key_secret fields."
  value       = { for key, secret in aws_secretsmanager_secret.provider : key => secret.name }
}

output "ingress_tls_secret_arns" {
  description = "Ingress TLS secret ARN per region role."
  value = {
    primary   = aws_secretsmanager_secret.ingress_tls.arn
    secondary = replace(aws_secretsmanager_secret.ingress_tls.arn, ":${data.aws_region.primary.name}:", ":${var.secondary_region}:")
  }
}

output "provider_secret_arns" {
  description = "Secret ARNs per region (the replica ARN differs only by region)."
  value = {
    primary = [for secret in aws_secretsmanager_secret.provider : secret.arn]
    secondary = [
      for secret in aws_secretsmanager_secret.provider :
      replace(secret.arn, ":${data.aws_region.primary.name}:", ":${var.secondary_region}:")
    ]
  }
}
