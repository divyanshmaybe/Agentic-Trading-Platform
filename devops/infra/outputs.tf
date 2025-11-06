output "cluster_id" {
  description = "Kubernetes cluster ID"
  value       = civo_kubernetes_cluster.main.id
}

output "cluster_name" {
  description = "Kubernetes cluster name"
  value       = civo_kubernetes_cluster.main.name
}

output "api_endpoint" {
  description = "Kubernetes API endpoint"
  value       = civo_kubernetes_cluster.main.api_endpoint
}

output "kubeconfig" {
  description = "Kubeconfig for accessing the cluster"
  value       = data.civo_kubernetes_cluster.main.kubeconfig
  sensitive   = true
}

output "cert_manager_namespace" {
  description = "Cert-manager namespace"
  value       = kubernetes_namespace.cert_manager.metadata[0].name
}

output "ingress_nginx_namespace" {
  description = "Ingress Nginx namespace"
  value       = kubernetes_namespace.ingress_nginx.metadata[0].name
}

output "external_dns_namespace" {
  description = "External DNS namespace"
  value       = kubernetes_namespace.external_dns.metadata[0].name
}

output "monitoring_namespace" {
  description = "Monitoring namespace"
  value       = kubernetes_namespace.monitoring.metadata[0].name
}

output "thanos_s3_bucket_name" {
  description = "AWS S3 bucket name for Thanos"
  value       = aws_s3_bucket.thanos.bucket
}

output "aws_region" {
  description = "AWS region for S3"
  value       = var.aws_region
}
