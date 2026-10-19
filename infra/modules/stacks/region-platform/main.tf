/**
 * Cluster platform for one region. Kept in a separate state from the foundation because
 * its Helm provider needs a running cluster to plan against.
 */

module "platform" {
  source = "../../platform"

  cluster_name           = var.foundation.cluster_name
  region                 = var.region
  vpc_id                 = var.foundation.vpc_id
  public_subnet_ids      = var.foundation.public_subnet_ids
  private_subnet_ids     = var.foundation.private_subnet_ids
  node_security_group_id = var.foundation.node_security_group_id
  karpenter_queue_name   = var.foundation.karpenter_queue_name
  client_cidrs           = var.client_cidrs
  certificate_arn        = var.certificate_arn
  access_logs_bucket     = var.access_logs_bucket
  external_secret_arns   = [var.foundation.valkey_auth_secret_arn, var.ingress_tls_secret_arn]
  chart_versions         = var.chart_versions
  alarm_topic_arn        = var.alarm_topic_arn
  tags                   = var.tags
}
