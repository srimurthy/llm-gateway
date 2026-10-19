/**
 * One name for the whole service. Latency routing sends each caller to the nearest
 * region's public NLB; a region whose ingress alarm fires drops out of the answers.
 *
 * evaluate_target_health is off: the NLB looks healthy to Route 53 even with no healthy
 * pods behind the ALB, so the alarm-backed health check is the signal that counts.
 */

resource "aws_route53_record" "api" {
  for_each = var.regional_endpoints

  zone_id         = var.zone_id
  name            = var.record_name
  type            = "A"
  set_identifier  = each.key
  health_check_id = each.value.health_check_id

  latency_routing_policy {
    region = each.key
  }

  alias {
    name                   = each.value.dns_name
    zone_id                = each.value.zone_id
    evaluate_target_health = false
  }
}
