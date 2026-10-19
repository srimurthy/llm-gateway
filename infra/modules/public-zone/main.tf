/**
 * Public DNS zone for the gateway and one ACM certificate per region.
 *
 * ACM issues the same DNS validation record for the same name in the same account, in
 * every region, so one record validates both certificates.
 */

resource "aws_route53_zone" "this" {
  provider = aws.primary

  name    = var.zone_name
  comment = "LLM gateway (public, access restricted to corporate egress IPs at the NLB)"
  tags    = var.tags
}

resource "aws_acm_certificate" "primary" {
  provider = aws.primary

  domain_name       = var.api_hostname
  validation_method = "DNS"
  tags              = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate" "secondary" {
  provider = aws.secondary

  domain_name       = var.api_hostname
  validation_method = "DNS"
  tags              = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  provider = aws.primary
  for_each = {
    for option in aws_acm_certificate.primary.domain_validation_options :
    option.domain_name => option
  }

  zone_id         = aws_route53_zone.this.zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "primary" {
  provider = aws.primary

  certificate_arn         = aws_acm_certificate.primary.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}

resource "aws_acm_certificate_validation" "secondary" {
  provider = aws.secondary

  certificate_arn         = aws_acm_certificate.secondary.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}
