/**
 * AWS WAF on the internal ALB.
 *
 * LLM prompts routinely contain code, HTML, SQL and file paths, and they are large. The
 * body-inspecting rules in the common rule set would block legitimate requests, so they
 * run in COUNT mode: visible in WAF logs and metrics, never blocking. Header, URI and
 * bad-input rules still block. Rate limits live in Istio (L1, L2) and the gateway (L3).
 */

locals {
  common_rules_count_only = [
    "SizeRestrictions_BODY",
    "CrossSiteScripting_BODY",
    "GenericLFI_BODY",
    "GenericRFI_BODY",
    "EC2MetaDataSSRF_BODY",
  ]
}

resource "aws_wafv2_web_acl" "alb" {
  count = var.enable_waf ? 1 : 0

  name        = "${var.cluster_name}-edge"
  description = "Managed protections for the LLM gateway edge"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-ip-reputation"
    priority = 10

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-common"
    priority = 30

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        dynamic "rule_action_override" {
          for_each = local.common_rules_count_only
          content {
            name = rule_action_override.value
            action_to_use {
              count {}
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.cluster_name}-edge"
    sampled_requests_enabled   = true
  }

  tags = var.tags
}

resource "aws_wafv2_web_acl_association" "alb" {
  count = var.enable_waf ? 1 : 0

  resource_arn = aws_lb.internal.arn
  web_acl_arn  = aws_wafv2_web_acl.alb[0].arn
}

# WAF requires the log group name to start with aws-waf-logs-.
resource "aws_cloudwatch_log_group" "waf" {
  count = var.enable_waf ? 1 : 0

  name              = "aws-waf-logs-${var.cluster_name}"
  retention_in_days = 90
  tags              = var.tags
}

resource "aws_wafv2_web_acl_logging_configuration" "alb" {
  count = var.enable_waf ? 1 : 0

  resource_arn            = aws_wafv2_web_acl.alb[0].arn
  log_destination_configs = [aws_cloudwatch_log_group.waf[0].arn]

  # Never log credentials.
  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
}
