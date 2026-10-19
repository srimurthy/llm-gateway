variable "zone_id" {
  description = "Public hosted zone that holds the record."
  type        = string
}

variable "record_name" {
  description = "Hostname clients call."
  type        = string
}

variable "regional_endpoints" {
  description = "Per-region public NLB alias target and the health check that guards it."
  type = map(object({
    dns_name        = string
    zone_id         = string
    health_check_id = string
  }))
}
