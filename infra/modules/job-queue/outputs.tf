output "queue_url" {
  description = "Job queue URL (LLMGW_JOBS_QUEUE_URL)."
  value       = aws_sqs_queue.this.id
}

output "queue_arn" {
  description = "Job queue ARN."
  value       = aws_sqs_queue.this.arn
}

output "dlq_arn" {
  description = "Dead-letter queue ARN."
  value       = aws_sqs_queue.dlq.arn
}
