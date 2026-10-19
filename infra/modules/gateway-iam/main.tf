/**
 * Least-privilege roles for the gateway, bound to Kubernetes service accounts with EKS
 * Pod Identity. The API and the worker get separate roles: only the API can enqueue
 * jobs, and only the worker can consume them. The vLLM pods get read access to the
 * model weights bucket and nothing else.
 */

data "aws_region" "current" {}

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "shared" {
  statement {
    sid       = "InvokeApprovedModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.bedrock_resource_arns
  }

  statement {
    sid       = "ReadTenantPolicies"
    actions   = ["dynamodb:GetItem"]
    resources = [var.table_arns.tenants]
  }

  statement {
    sid       = "WriteUsageLedger"
    actions   = ["dynamodb:UpdateItem"]
    resources = [var.table_arns.usage]
  }

  statement {
    sid       = "ReadProviderKeys"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.provider_secret_arns
  }

  statement {
    sid       = "DecryptViaServices"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = var.kms_key_arns

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "dynamodb.${data.aws_region.current.name}.amazonaws.com",
        "secretsmanager.${data.aws_region.current.name}.amazonaws.com",
      ]
    }
  }
}

data "aws_iam_policy_document" "api" {
  source_policy_documents = [data.aws_iam_policy_document.shared.json]

  statement {
    sid       = "ManageOwnJobs"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [var.table_arns.jobs]
  }

  statement {
    sid       = "EnqueueJobs"
    actions   = ["sqs:SendMessage"]
    resources = [var.queue_arn]
  }
}

data "aws_iam_policy_document" "worker" {
  source_policy_documents = [data.aws_iam_policy_document.shared.json]

  statement {
    sid       = "CompleteJobs"
    actions   = ["dynamodb:UpdateItem"]
    resources = [var.table_arns.jobs]
  }

  statement {
    sid       = "ConsumeJobs"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility"]
    resources = [var.queue_arn]
  }
}

data "aws_iam_policy_document" "slm" {
  count = var.model_bucket_arn == null ? 0 : 1

  statement {
    sid       = "ListModelBucket"
    actions   = ["s3:ListBucket"]
    resources = [var.model_bucket_arn]
  }

  statement {
    sid       = "ReadModelWeights"
    actions   = ["s3:GetObject"]
    resources = ["${var.model_bucket_arn}/*"]
  }
}

locals {
  slm_role = var.model_bucket_arn == null ? {} : {
    slm = {
      namespace       = var.slm_namespace
      service_account = "vllm"
      policy          = data.aws_iam_policy_document.slm[0].json
    }
  }

  roles = merge(local.slm_role, {
    api = {
      namespace       = var.namespace
      service_account = var.api_service_account
      policy          = data.aws_iam_policy_document.api.json
    }
    worker = {
      namespace       = var.namespace
      service_account = var.worker_service_account
      policy          = data.aws_iam_policy_document.worker.json
    }
  })
}

resource "aws_iam_role" "this" {
  for_each = local.roles

  name               = "${var.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "this" {
  for_each = local.roles

  name   = "${var.name}-${each.key}"
  role   = aws_iam_role.this[each.key].id
  policy = each.value.policy
}

resource "aws_eks_pod_identity_association" "this" {
  for_each = local.roles

  cluster_name    = var.cluster_name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.this[each.key].arn
  tags            = var.tags
}
