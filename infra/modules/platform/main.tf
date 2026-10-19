/**
 * Cluster platform: the controllers and meshes the gateway runs on.
 *
 * Installed here (not by Argo CD) because the rest depends on them: Argo CD itself,
 * the CRDs it applies (Istio, Karpenter, External Secrets) and the NLB binding.
 * Application-level resources live in deploy/ and are applied by Argo CD.
 */

locals {
  istio_repository = "https://istio-release.storage.googleapis.com/charts"

  # Platform controllers run on the tainted system node group.
  system_placement = {
    nodeSelector = { "node-role" = "system" }
    tolerations  = [{ key = "CriticalAddonsOnly", operator = "Exists" }]
  }
}

module "lb_controller_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12"

  name                            = "${var.cluster_name}-aws-lbc"
  attach_aws_lb_controller_policy = true

  associations = {
    this = {
      cluster_name    = var.cluster_name
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
    }
  }

  tags = var.tags
}

module "external_secrets_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.12"

  name                                  = "${var.cluster_name}-external-secrets"
  attach_external_secrets_policy        = true
  external_secrets_secrets_manager_arns = var.external_secret_arns
  external_secrets_create_permission    = false

  associations = {
    this = {
      cluster_name    = var.cluster_name
      namespace       = "external-secrets"
      service_account = "external-secrets"
    }
  }

  tags = var.tags
}

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.chart_versions.aws_load_balancer_controller

  values = [yamlencode(merge(local.system_placement, {
    clusterName    = var.cluster_name
    region         = var.region
    vpcId          = var.vpc_id
    replicaCount   = 2
    serviceAccount = { name = "aws-load-balancer-controller" }
  }))]

  depends_on = [module.lb_controller_pod_identity]
}

resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = var.chart_versions.karpenter

  values = [yamlencode(merge(local.system_placement, {
    replicas       = 2
    serviceAccount = { name = "karpenter" }
    settings = {
      clusterName       = var.cluster_name
      interruptionQueue = var.karpenter_queue_name
    }
    controller = {
      resources = {
        requests = { cpu = "500m", memory = "1Gi" }
        limits   = { memory = "1Gi" }
      }
    }
  }))]
}

resource "helm_release" "istio_base" {
  name             = "istio-base"
  namespace        = "istio-system"
  create_namespace = true
  repository       = local.istio_repository
  chart            = "base"
  version          = var.chart_versions.istio

  values = [yamlencode({ defaultRevision = "default" })]
}

resource "helm_release" "istiod" {
  name       = "istiod"
  namespace  = "istio-system"
  repository = local.istio_repository
  chart      = "istiod"
  version    = var.chart_versions.istio

  values = [yamlencode({
    pilot = merge(local.system_placement, {
      autoscaleMin = 2
      autoscaleMax = 5
      resources = {
        requests = { cpu = "500m", memory = "2Gi" }
      }
    })
    meshConfig = {
      accessLogFile     = "/dev/stdout"
      accessLogEncoding = "JSON"
      # Only destinations registered as ServiceEntries are reachable from the mesh.
      outboundTrafficPolicy = { mode = "REGISTRY_ONLY" }
      enablePrometheusMerge = true
      defaultConfig = {
        holdApplicationUntilProxyStarts = true
      }
    }
  })]

  depends_on = [helm_release.istio_base]
}

resource "helm_release" "istio_ingress" {
  name             = "istio-ingressgateway"
  namespace        = "istio-ingress"
  create_namespace = true
  repository       = local.istio_repository
  chart            = "gateway"
  version          = var.chart_versions.istio

  values = [yamlencode({
    labels = { istio = "ingressgateway" }
    # The Terraform-owned NLB targets pod IPs, so the Service stays internal.
    service = {
      type = "ClusterIP"
      ports = [
        { name = "status-port", port = 15021, targetPort = 15021, protocol = "TCP" },
        { name = "https", port = 443, targetPort = 8443, protocol = "TCP" },
      ]
    }
    autoscaling = {
      enabled                        = true
      minReplicas                    = 3
      maxReplicas                    = 20
      targetCPUUtilizationPercentage = 60
    }
    podDisruptionBudget = { minAvailable = 2 }
    topologySpreadConstraints = [{
      maxSkew           = 1
      topologyKey       = "topology.kubernetes.io/zone"
      whenUnsatisfiable = "DoNotSchedule"
      labelSelector     = { matchLabels = { istio = "ingressgateway" } }
    }]
    resources = {
      requests = { cpu = "1", memory = "1Gi" }
      limits   = { memory = "2Gi" }
    }
    terminationGracePeriodSeconds = 330
  })]

  depends_on = [helm_release.istiod]
}

resource "helm_release" "istio_egress" {
  name             = "istio-egressgateway"
  namespace        = "istio-egress"
  create_namespace = true
  repository       = local.istio_repository
  chart            = "gateway"
  version          = var.chart_versions.istio

  values = [yamlencode({
    labels = { istio = "egressgateway" }
    service = {
      type = "ClusterIP"
      ports = [
        { name = "status-port", port = 15021, targetPort = 15021, protocol = "TCP" },
        { name = "tls", port = 443, targetPort = 8443, protocol = "TCP" },
      ]
    }
    autoscaling = {
      enabled                        = true
      minReplicas                    = 2
      maxReplicas                    = 10
      targetCPUUtilizationPercentage = 60
    }
    podDisruptionBudget = { minAvailable = 1 }
    topologySpreadConstraints = [{
      maxSkew           = 1
      topologyKey       = "topology.kubernetes.io/zone"
      whenUnsatisfiable = "ScheduleAnyway"
      labelSelector     = { matchLabels = { istio = "egressgateway" } }
    }]
  })]

  depends_on = [helm_release.istiod]
}

resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = var.chart_versions.external_secrets

  values = [yamlencode(merge(local.system_placement, {
    installCRDs    = true
    serviceAccount = { name = "external-secrets" }
  }))]

  depends_on = [module.external_secrets_pod_identity]
}

resource "helm_release" "argo_cd" {
  count = var.enable_argo_cd ? 1 : 0

  name             = "argo-cd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.chart_versions.argo_cd

  values = [yamlencode({
    global = local.system_placement
    server = { service = { type = "ClusterIP" } }
  })]
}
