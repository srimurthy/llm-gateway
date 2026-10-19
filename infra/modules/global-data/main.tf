/**
 * Data shared by both regions.
 *
 * - DynamoDB global tables: tenant policies, the usage ledger and async jobs. Either
 *   region can serve any tenant or job after a failover.
 * - A multi-Region KMS key, so each replica is encrypted with a key in its own region.
 * - Provider API key secrets, replicated to the secondary region.
 */

locals {
  tables = {
    tenants = { hash_key = "tenant_id", range_key = null, ttl_attribute = null }
    usage   = { hash_key = "pk", range_key = "sk", ttl_attribute = "expires_at" }
    jobs    = { hash_key = "job_id", range_key = null, ttl_attribute = "expires_at" }
  }
}

resource "aws_kms_key" "data" {
  provider = aws.primary

  description             = "${var.name_prefix} shared data (DynamoDB, Secrets Manager)"
  multi_region            = true
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = var.tags
}

resource "aws_kms_alias" "data" {
  provider = aws.primary

  name          = "alias/${var.name_prefix}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_kms_replica_key" "data" {
  provider = aws.secondary

  description             = "${var.name_prefix} shared data (replica)"
  primary_key_arn         = aws_kms_key.data.arn
  deletion_window_in_days = 30
  tags                    = var.tags
}

resource "aws_kms_alias" "data_replica" {
  provider = aws.secondary

  name          = "alias/${var.name_prefix}-data"
  target_key_id = aws_kms_replica_key.data.key_id
}

resource "aws_dynamodb_table" "this" {
  provider = aws.primary
  for_each = local.tables

  name         = "${var.name_prefix}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash_key
  range_key    = each.value.range_key

  # Global tables replicate through streams.
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  deletion_protection_enabled = true

  attribute {
    name = each.value.hash_key
    type = "S"
  }

  dynamic "attribute" {
    for_each = each.value.range_key == null ? [] : [each.value.range_key]
    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl_attribute == null ? [] : [each.value.ttl_attribute]
    content {
      attribute_name = ttl.value
      enabled        = true
    }
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn
  }

  replica {
    region_name            = var.secondary_region
    kms_key_arn            = aws_kms_replica_key.data.arn
    point_in_time_recovery = true
    propagate_tags         = true
  }

  tags = var.tags
}

# Ingress TLS certificate from the corporate CA, as JSON {"tls.crt": ..., "tls.key": ...}.
# Value written out of band; External Secrets syncs it to the Istio ingress gateway.
resource "aws_secretsmanager_secret" "ingress_tls" {
  provider = aws.primary

  name                    = "${var.name_prefix}/ingress-tls"
  description             = "TLS certificate and key for the gateway's internal hostname."
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30

  replica {
    region     = var.secondary_region
    kms_key_id = aws_kms_replica_key.data.arn
  }

  tags = var.tags
}

resource "aws_secretsmanager_secret" "provider" {
  provider = aws.primary
  for_each = var.provider_secret_names

  name                    = "${var.name_prefix}/${each.key}"
  description             = "API key for ${each.key}. Value managed outside Terraform."
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30

  replica {
    region     = var.secondary_region
    kms_key_id = aws_kms_replica_key.data.arn
  }

  tags = var.tags
}
