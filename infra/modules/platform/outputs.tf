output "public_nlb_dns_name" {
  description = "Public NLB DNS name (Route 53 alias target)."
  value       = aws_lb.public.dns_name
}

output "public_nlb_zone_id" {
  description = "Public NLB hosted zone ID (Route 53 alias target)."
  value       = aws_lb.public.zone_id
}

output "public_nlb_ips" {
  description = "Static public IPs of the NLB, for corporate egress firewall allowlists."
  value       = aws_eip.nlb[*].public_ip
}

output "ingress_health_check_id" {
  description = "Route 53 health check that follows the ingress alarm."
  value       = aws_route53_health_check.ingress.id
}
