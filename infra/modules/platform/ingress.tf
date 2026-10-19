/**
 * Edge: public NLB -> internal ALB -> Istio ingress gateway pods.
 *
 * - NLB (public subnets, one Elastic IP per AZ): the only internet-facing piece. Its
 *   security group admits only the corporate egress ranges, and its static IPs can be
 *   allowlisted by corporate firewalls. TCP passthrough on 443.
 * - ALB (private subnets), registered as the NLB's target: terminates TLS with the ACM
 *   certificate, runs AWS WAF, drops malformed headers, and re-encrypts to Istio.
 * - Istio ingress gateway pods, bound to the ALB target group with a TargetGroupBinding.
 *   Istio then checks the JWT and applies rate limits L1 and L2.
 *
 * Terraform owns both load balancers (not a Kubernetes Service), so their ARNs stay
 * stable for alarms, DNS and the health check, and a Service change cannot delete them.
 */

locals {
  name_prefix = substr(var.cluster_name, 0, 24)
  pod_ports = {
    https  = 8443
    health = 15021
  }
  access_logs = var.access_logs_bucket == null ? [] : [var.access_logs_bucket]
}

# ---------------------------------------------------------------- public NLB

resource "aws_eip" "nlb" {
  count = length(var.public_subnet_ids)

  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.cluster_name}-nlb-${count.index}" })
}

resource "aws_security_group" "nlb" {
  name_prefix = "${var.cluster_name}-public-nlb-"
  description = "Public NLB: HTTPS from corporate egress ranges only"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.cluster_name}-public-nlb" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "nlb_from_corporate" {
  for_each = toset(var.client_cidrs)

  security_group_id = aws_security_group.nlb.id
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS from corporate egress ${each.value}"
}

resource "aws_vpc_security_group_egress_rule" "nlb_to_alb" {
  security_group_id            = aws_security_group.nlb.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "To the internal ALB"
}

resource "aws_lb" "public" {
  name                             = "${local.name_prefix}-public"
  internal                         = false
  load_balancer_type               = "network"
  security_groups                  = [aws_security_group.nlb.id]
  enable_cross_zone_load_balancing = true
  enable_deletion_protection       = var.deletion_protection

  dynamic "subnet_mapping" {
    for_each = var.public_subnet_ids
    content {
      subnet_id     = subnet_mapping.value
      allocation_id = aws_eip.nlb[subnet_mapping.key].id
    }
  }

  dynamic "access_logs" {
    for_each = local.access_logs
    content {
      bucket  = access_logs.value
      prefix  = "${var.cluster_name}/nlb"
      enabled = true
    }
  }

  tags = var.tags
}

resource "aws_lb_target_group" "alb" {
  name        = "${local.name_prefix}-to-alb"
  vpc_id      = var.vpc_id
  target_type = "alb"
  protocol    = "TCP"
  port        = 443

  # NLB health checks an ALB target over HTTP(S). A fixed-response rule on the ALB
  # answers them, so the NLB tests the ALB itself; pod health is watched by the alarm.
  health_check {
    protocol            = "HTTPS"
    path                = "/lb-health"
    matcher             = "200"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = var.tags
}

resource "aws_lb_target_group_attachment" "alb" {
  target_group_arn = aws_lb_target_group.alb.arn
  target_id        = aws_lb.internal.arn
  port             = 443

  depends_on = [aws_lb_listener.alb_https]
}

resource "aws_lb_listener" "nlb_tls_passthrough" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.alb.arn
  }

  tags = var.tags
}

# ---------------------------------------------------------------- internal ALB

resource "aws_security_group" "alb" {
  name_prefix = "${var.cluster_name}-internal-alb-"
  description = "Internal ALB: HTTPS from the public NLB only"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.cluster_name}-internal-alb" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_nlb" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.nlb.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS from the public NLB"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_pods" {
  for_each = local.pod_ports

  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = var.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
  description                  = "To Istio ingress pods (${each.key})"
}

resource "aws_vpc_security_group_ingress_rule" "pods_from_alb" {
  for_each = local.pod_ports

  security_group_id            = var.node_security_group_id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
  description                  = "From the internal ALB (${each.key})"
}

resource "aws_lb" "internal" {
  name                       = "${local.name_prefix}-internal"
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = var.private_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  enable_deletion_protection = var.deletion_protection

  drop_invalid_header_fields = true
  desync_mitigation_mode     = "strictest"
  # Above the 300s request timeout, so a slow stream is ended by Istio, not cut here.
  idle_timeout = 360

  dynamic "access_logs" {
    for_each = local.access_logs
    content {
      bucket  = access_logs.value
      prefix  = "${var.cluster_name}/alb"
      enabled = true
    }
  }

  tags = var.tags
}

resource "aws_lb_target_group" "istio" {
  name        = "${local.name_prefix}-istio"
  vpc_id      = var.vpc_id
  target_type = "ip"
  protocol    = "HTTPS" # re-encrypted: TLS from the client's edge all the way to the mesh
  port        = local.pod_ports.https

  load_balancing_algorithm_type = "least_outstanding_requests"
  # Long enough for in-flight streams to finish when an ingress pod drains.
  deregistration_delay = 300

  health_check {
    protocol            = "HTTP"
    port                = tostring(local.pod_ports.health)
    path                = "/healthz/ready"
    matcher             = "200"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = var.tags
}

resource "aws_lb_listener" "alb_https" {
  load_balancer_arn = aws_lb.internal.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.istio.arn
  }

  tags = var.tags
}

resource "aws_lb_listener_rule" "lb_health" {
  listener_arn = aws_lb_listener.alb_https.arn
  priority     = 1

  condition {
    path_pattern {
      values = ["/lb-health"]
    }
  }

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "ok"
      status_code  = "200"
    }
  }

  tags = var.tags
}

resource "helm_release" "ingress_binding" {
  name      = "ingress-binding"
  namespace = "istio-ingress"
  chart     = "${path.module}/charts/ingress-binding"

  values = [yamlencode({
    targetGroupArn = aws_lb_target_group.istio.arn
    serviceName    = "istio-ingressgateway"
    servicePort    = 443
  })]

  depends_on = [helm_release.aws_load_balancer_controller, helm_release.istio_ingress]
}

# ---------------------------------------------------------------- region health

# Route 53 follows this alarm: no healthy Istio ingress pods behind the ALB means the
# region drops out of DNS. (Endpoint health checks would need the SG to admit Route 53's
# checkers from the internet; the alarm needs no extra exposure.)
resource "aws_cloudwatch_metric_alarm" "ingress_unhealthy" {
  alarm_name          = "${var.cluster_name}-ingress-no-healthy-targets"
  alarm_description   = "No healthy Istio ingress pods behind the ALB. Route 53 fails over away from this region."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  dimensions = {
    LoadBalancer = aws_lb.internal.arn_suffix
    TargetGroup  = aws_lb_target_group.istio.arn_suffix
  }

  alarm_actions = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
  ok_actions    = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
  tags          = var.tags
}

resource "aws_route53_health_check" "ingress" {
  type                            = "CLOUDWATCH_METRIC"
  cloudwatch_alarm_name           = aws_cloudwatch_metric_alarm.ingress_unhealthy.alarm_name
  cloudwatch_alarm_region         = var.region
  insufficient_data_health_status = "LastKnownStatus"
  tags                            = merge(var.tags, { Name = "${var.cluster_name}-ingress" })
}
