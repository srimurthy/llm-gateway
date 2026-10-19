/**
 * Valkey (cluster mode, Multi-AZ, TLS, AUTH) for rate-limit counters.
 *
 * Shared by the Envoy ratelimit service (L2, requests per minute) and the gateway pods
 * (L3, tokens per minute). The data is ephemeral, so there are no snapshots: after a
 * total loss every bucket starts full, which errs toward availability.
 *
 * The AUTH token is generated here and lands in Terraform state. State is encrypted in
 * S3 with restricted access; see infra/README.md.
 */

resource "random_password" "auth" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "auth" {
  name                    = "${var.name}/valkey-auth"
  description             = "AUTH token for the ${var.name} Valkey cluster"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 7
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "auth" {
  secret_id     = aws_secretsmanager_secret.auth.id
  secret_string = random_password.auth.result
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-valkey-"
  description = "Valkey access from EKS nodes"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-valkey" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "from_clients" {
  for_each = toset(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Valkey from ${each.value}"
}

resource "aws_elasticache_parameter_group" "this" {
  name        = "${var.name}-valkey8"
  family      = "valkey8"
  description = "Cluster mode enabled"

  parameter {
    name  = "cluster-enabled"
    value = "yes"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "slow_log" {
  name              = "/aws/elasticache/${var.name}/slow-log"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = var.name
  description          = "LLM gateway rate-limit counters"

  engine               = "valkey"
  engine_version       = "8.0"
  node_type            = var.node_type
  parameter_group_name = aws_elasticache_parameter_group.this.name
  port                 = 6379

  num_node_groups         = var.shards
  replicas_per_node_group = var.replicas_per_shard

  automatic_failover_enabled = true
  multi_az_enabled           = true

  subnet_group_name  = var.subnet_group_name
  security_group_ids = [aws_security_group.this.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"
  auth_token                 = random_password.auth.result
  auth_token_update_strategy = "ROTATE"

  snapshot_retention_limit = 0
  maintenance_window       = "sun:05:00-sun:06:00"
  apply_immediately        = false

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.slow_log.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }

  tags = var.tags
}
