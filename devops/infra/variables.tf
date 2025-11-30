variable "civo_region" {
  description = "Civo region"
  type        = string
  default     = "mum1"
}

variable "cluster_name" {
  description = "Kubernetes cluster name"
  type        = string
  default     = "pathway-submission-cluster"
}

variable "node_size" {
  description = "Node size for the cluster"
  type        = string
  default     = "g4s.kube.medium"
}

variable "node_count" {
  description = "Number of nodes in the cluster"
  type        = number
  default     = 3
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token for external-dns"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for the domain"
  type        = string
}

variable "letsencrypt_email" {
  description = "Email address for Let's Encrypt certificate notifications"
  type        = string
}

variable "prometheus_storage_size" {
  description = "Storage size for Prometheus persistent volume"
  type        = string
  default     = "10Gi"
}

variable "grafana_storage_size" {
  description = "Storage size for Grafana persistent volume"
  type        = string
  default     = "5Gi"
}

variable "aws_region" {
  description = "AWS region for S3 (used by Thanos object storage)"
  type        = string
  default     = "ap-south-1"
}

variable "thanos_s3_bucket_name" {
  description = "Optional: predefine the S3 bucket name for Thanos. If empty, a name will be generated."
  type        = string
  default     = "terraform-k8s-thanos-metrics"
}

variable "aws_access_key_id" {
  description = "AWS access key ID used by the AWS provider (optional; can also use env/credentials file)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "aws_secret_access_key" {
  description = "AWS secret access key used by the AWS provider (optional; can also use env/credentials file)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "argocd_github_repo_url" {
  description = "GitHub repository URL for ArgoCD"
  type        = string
  default     = ""
}

variable "argocd_github_repo_password" {
  description = "GitHub token/password for ArgoCD repository access"
  type        = string
  sensitive   = true
  default     = ""
}

variable "argocd_github_username" {
  description = "GitHub username for ArgoCD repository access"
  type        = string
}
