output "api_role_arn" {
  description = "Role assumed by the API pods."
  value       = aws_iam_role.this["api"].arn
}

output "worker_role_arn" {
  description = "Role assumed by the job worker pods."
  value       = aws_iam_role.this["worker"].arn
}
