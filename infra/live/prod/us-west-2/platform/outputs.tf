output "platform" {
  description = "Public NLB, its static IPs and the health check, read by the DNS stack."
  value       = module.platform
}
