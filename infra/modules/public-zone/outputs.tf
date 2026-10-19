output "zone_id" {
  description = "Public hosted zone ID."
  value       = aws_route53_zone.this.zone_id
}

output "name_servers" {
  description = "Delegate the zone to these from the parent domain."
  value       = aws_route53_zone.this.name_servers
}

output "certificate_arns" {
  description = "Validated ACM certificate ARN per region role (primary, secondary)."
  value = {
    primary   = aws_acm_certificate_validation.primary.certificate_arn
    secondary = aws_acm_certificate_validation.secondary.certificate_arn
  }
}
