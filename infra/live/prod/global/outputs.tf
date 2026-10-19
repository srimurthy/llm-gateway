output "zone_id" {
  description = "Public hosted zone ID."
  value       = module.public_zone.zone_id
}

output "name_servers" {
  description = "Name servers to delegate the zone to from the parent domain."
  value       = module.public_zone.name_servers
}

output "certificate_arns" {
  description = "ACM certificate ARN per region role (primary, secondary)."
  value       = module.public_zone.certificate_arns
}

output "table_names" {
  description = "Global table names."
  value       = module.global_data.table_names
}

output "kms_key_arns" {
  description = "Data key ARN per region role (primary, secondary)."
  value       = module.global_data.kms_key_arns
}

output "provider_secret_ids" {
  description = "Secret IDs for the routing file."
  value       = module.global_data.provider_secret_ids
}

output "ingress_tls_secret_arns" {
  description = "Ingress TLS secret ARN per region role (primary, secondary)."
  value       = module.global_data.ingress_tls_secret_arns
}

output "provider_secret_arns" {
  description = "Secret ARNs per region role (primary, secondary)."
  value       = module.global_data.provider_secret_arns
}
