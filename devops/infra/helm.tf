resource "kubernetes_namespace" "ingress_nginx" {
  metadata {
    name = "ingress-nginx"
  }

  depends_on = [civo_kubernetes_cluster.main]
}

resource "helm_release" "nginx_ingress" {
  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  namespace  = kubernetes_namespace.ingress_nginx.metadata[0].name
  version    = "4.11.3"

  timeout = 600
  wait    = true

  set {
    name  = "controller.service.type"
    value = "LoadBalancer"
  }

  depends_on = [kubernetes_namespace.ingress_nginx]

  lifecycle {
    create_before_destroy = false
  }
}

resource "kubernetes_namespace" "cert_manager" {
  metadata {
    name = "cert-manager"
  }

  depends_on = [civo_kubernetes_cluster.main]
}

resource "helm_release" "cert_manager" {
  name       = "cert-manager"
  repository = "https://charts.jetstack.io"
  chart      = "cert-manager"
  namespace  = kubernetes_namespace.cert_manager.metadata[0].name
  version    = "v1.15.3"

  timeout = 600
  wait    = true

  set {
    name  = "installCRDs"
    value = "true"
  }

  depends_on = [kubernetes_namespace.cert_manager]

  lifecycle {
    create_before_destroy = false
  }
}

resource "kubernetes_namespace" "external_dns" {
  metadata {
    name = "external-dns"
  }

  depends_on = [civo_kubernetes_cluster.main]
}

resource "kubernetes_secret" "cloudflare_api_token" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = kubernetes_namespace.external_dns.metadata[0].name
  }

  data = {
    cloudflare_api_token = var.cloudflare_api_token
  }

  type = "Opaque"

  depends_on = [kubernetes_namespace.external_dns]
}

resource "helm_release" "external_dns" {
  name       = "external-dns"
  repository = "https://kubernetes-sigs.github.io/external-dns"
  chart      = "external-dns"
  namespace  = kubernetes_namespace.external_dns.metadata[0].name
  version    = "1.19.0"

  timeout = 600
  wait    = true

  set {
    name  = "provider.name"
    value = "cloudflare"
  }

  set {
    name  = "env[0].name"
    value = "CF_API_TOKEN"
  }

  set {
    name  = "env[0].valueFrom.secretKeyRef.name"
    value = kubernetes_secret.cloudflare_api_token.metadata[0].name
  }

  set {
    name  = "env[0].valueFrom.secretKeyRef.key"
    value = "cloudflare_api_token"
  }

  set {
    name  = "domainFilters[0]"
    value = "team65.space"
  }

  set {
    name  = "zoneIdFilters[0]"
    value = var.cloudflare_zone_id
  }

  set {
    name  = "policy"
    value = "sync"
  }

  set {
    name  = "txtOwnerId"
    value = var.cluster_name
  }

  depends_on = [kubernetes_namespace.external_dns, kubernetes_secret.cloudflare_api_token]

  lifecycle {
    create_before_destroy = false
  }
}

# AWS S3 for Thanos (replaces Civo object storage)
resource "random_id" "thanos_bucket_suffix" {
  byte_length = 2
}

resource "aws_s3_bucket" "thanos" {
  bucket        = var.thanos_s3_bucket_name != "" ? var.thanos_s3_bucket_name : "${var.cluster_name}-thanos-${random_id.thanos_bucket_suffix.hex}"
  force_destroy = true
}

resource "aws_iam_user" "thanos" {
  name = "${var.cluster_name}-thanos"
}

resource "aws_iam_user_policy" "thanos_bucket" {
  name = "${var.cluster_name}-thanos-bucket-policy"
  user = aws_iam_user.thanos.name

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["s3:ListBucket"],
        Resource = [aws_s3_bucket.thanos.arn]
      },
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListBucketMultipartUploads",
          "s3:ListMultipartUploadParts"
        ],
        Resource = ["${aws_s3_bucket.thanos.arn}/*"]
      }
    ]
  })
}

resource "aws_iam_access_key" "thanos" {
  user = aws_iam_user.thanos.name
}

# Monitoring namespace
resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }

  depends_on = [civo_kubernetes_cluster.main]
}

# Thanos object storage configuration secret for AWS S3
resource "kubernetes_secret" "thanos_objstore_config" {
  metadata {
    name      = "thanos-objstore-config"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }

  data = {
    "objstore.yml" = yamlencode({
      type = "S3"
      config = {
        bucket             = aws_s3_bucket.thanos.bucket
        region             = var.aws_region
        endpoint           = "s3.${var.aws_region}.amazonaws.com"
        access_key         = aws_iam_access_key.thanos.id
        secret_key         = aws_iam_access_key.thanos.secret
        insecure           = false
        signature_version2 = false
        bucket_lookup_type = "auto"
      }
    })
  }

  type = "Opaque"

  depends_on = [
    kubernetes_namespace.monitoring,
    aws_s3_bucket.thanos,
    aws_iam_access_key.thanos
  ]
}

# ArgoCD namespace
resource "kubernetes_namespace" "argocd" {
  metadata {
    name = "argocd"
  }

  depends_on = [civo_kubernetes_cluster.main]
}

resource "kubernetes_secret" "argocd_github_repo" {
  count = var.argocd_github_repo_url != "" && var.argocd_github_repo_password != "" ? 1 : 0

  metadata {
    name      = "github-repo-credentials"
    namespace = kubernetes_namespace.argocd.metadata[0].name
    labels = {
      "argocd.argoproj.io/secret-type" = "repository"
    }
  }

  data = {
    type     = "git"
    url      = var.argocd_github_repo_url
    username = var.argocd_github_username
    password = var.argocd_github_repo_password
  }

  type = "Opaque"

  depends_on = [kubernetes_namespace.argocd]
}
