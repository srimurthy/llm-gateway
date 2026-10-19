output "public_nlb_dns_name" {
  description = "Public NLB DNS name."
  value       = module.platform.public_nlb_dns_name
}

output "public_nlb_zone_id" {
  description = "Public NLB hosted zone ID."
  value       = module.platform.public_nlb_zone_id
}

output "public_nlb_ips" {
  description = "Static NLB IPs for corporate firewall allowlists."
  value       = module.platform.public_nlb_ips
}

output "ingress_health_check_id" {
  description = "Route 53 health check for this region."
  value       = module.platform.ingress_health_check_id
}
