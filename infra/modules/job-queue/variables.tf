variable "name" {
  description = "Queue name. The dead-letter queue gets a -dlq suffix."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "Must exceed the longest job (provider read timeout plus margin)."
  type        = number
  default     = 360
}

variable "max_receive_count" {
  description = <<-EOT
    Receives before a message moves to the DLQ. Deferred jobs (budget or provider limits)
    count as receives too, so this is set higher than for a typical queue.
  EOT
  type        = number
  default     = 30
}

variable "alarm_topic_arn" {
  description = "SNS topic for the dead-letter alarm. Null creates the alarm without actions."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
