terraform {
  required_version = ">= 1.0"

  required_providers {
    civo = {
      source  = "civo/civo"
      version = "~> 1.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

provider "civo" {
  region = var.civo_region
}

provider "aws" {
  region = var.aws_region
  access_key = var.aws_access_key_id
  secret_key = var.aws_secret_access_key
}

provider "helm" {
  kubernetes {
    host = try(
      yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).clusters[0].cluster.server,
      civo_kubernetes_cluster.main.api_endpoint
    )

    client_certificate = try(
      base64decode(yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).users[0].user["client-certificate-data"]),
      null
    )

    client_key = try(
      base64decode(yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).users[0].user["client-key-data"]),
      null
    )

    cluster_ca_certificate = try(
      base64decode(yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).clusters[0].cluster["certificate-authority-data"]),
      null
    )
  }
}

provider "kubernetes" {
  host = try(
    yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).clusters[0].cluster.server,
    civo_kubernetes_cluster.main.api_endpoint
  )

  client_certificate = try(
    base64decode(yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).users[0].user["client-certificate-data"]),
    null
  )

  client_key = try(
    base64decode(yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).users[0].user["client-key-data"]),
    null
  )

  cluster_ca_certificate = try(
    base64decode(yamldecode(data.civo_kubernetes_cluster.main.kubeconfig).clusters[0].cluster["certificate-authority-data"]),
    null
  )
}

