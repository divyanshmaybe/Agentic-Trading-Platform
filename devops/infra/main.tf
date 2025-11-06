resource "civo_kubernetes_cluster" "main" {
  name        = var.cluster_name
  region      = var.civo_region
  firewall_id = civo_firewall.cluster_firewall.id
  pools {
    size       = var.node_size
    node_count = var.node_count
  }
}

resource "civo_firewall" "cluster_firewall" {
  name                 = "${var.cluster_name}-firewall"
  create_default_rules = true
  region               = var.civo_region
}

data "civo_kubernetes_cluster" "main" {
  name = civo_kubernetes_cluster.main.name

  depends_on = [civo_kubernetes_cluster.main]
}

resource "local_file" "kubeconfig" {
  content         = data.civo_kubernetes_cluster.main.kubeconfig
  filename        = "${path.module}/kubeconfig"
  file_permission = "0600"

  depends_on = [data.civo_kubernetes_cluster.main]
}
