#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-agent-invest}"
KIND_CONFIG="${KIND_CONFIG:-${SCRIPT_DIR}/kind-config.yaml}"
INGRESS_MANIFEST="${INGRESS_MANIFEST:-https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml}"
CERT_MANAGER_MANIFEST="${CERT_MANAGER_MANIFEST:-https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml}"
ARGOCD_MANIFEST="${ARGOCD_MANIFEST:-${REPO_ROOT}/devops/argocd/argocd.yml}"
KUSTOMIZE_DIR="${KUSTOMIZE_DIR:-${SCRIPT_DIR}}"
# Set IMAGES environment variable with your DockerHub username
IMAGES="${IMAGES:-your-dockerhub-username/agent-invest-frontend:latest your-dockerhub-username/agent-invest-auth-server:latest your-dockerhub-username/agent-invest-portfolio-server:latest your-dockerhub-username/agent-invest-notification-server:latest}"
ARGOCD_PASSWORD=""

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required dependency: $1"
    exit 1
  fi
}

create_cluster() {
  if kind get clusters | grep -qx "${KIND_CLUSTER_NAME}"; then
    log "Kind cluster '${KIND_CLUSTER_NAME}' already exists. Skipping creation."
    return 1
  fi

  log "Creating Kind cluster '${KIND_CLUSTER_NAME}' using ${KIND_CONFIG}..."
  kind create cluster --name "${KIND_CLUSTER_NAME}" --config "${KIND_CONFIG}"
  return 0
}

install_ingress() {
  log "Installing nginx ingress controller..."
  kubectl apply -f "${INGRESS_MANIFEST}"

  log "Waiting for ingress controller to become ready..."
  kubectl wait --namespace ingress-nginx \
    --for=condition=Ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=180s
}

install_cert_manager() {
  if kubectl get ns cert-manager >/dev/null 2>&1; then
    log "cert-manager already installed. Skipping."
    return
  fi

  log "Installing cert-manager from ${CERT_MANAGER_MANIFEST}..."
  kubectl apply -f "${CERT_MANAGER_MANIFEST}"

  log "Waiting for cert-manager components to become ready..."
  kubectl wait --namespace cert-manager \
    --for=condition=Ready pod \
    --selector=app=cert-manager \
    --timeout=180s
}

install_argocd() {
  if kubectl get ns argocd >/dev/null 2>&1; then
    log "ArgoCD already installed. Skipping."
    return
  fi

  log "Installing ArgoCD..."
  kubectl create namespace argocd || true

  # Add ArgoCD Helm repo
  helm repo add argo https://argoproj.github.io/argo-helm || true
  helm repo update

  # Install ArgoCD with Helm
  helm install argocd argo/argo-cd \
    --namespace argocd \
    --version 7.6.12 \
    --set server.service.type=ClusterIP \
    --wait

  log "Waiting for ArgoCD to be ready..."
  kubectl wait --namespace argocd \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/name=argocd-server \
    --timeout=180s

  log "ArgoCD initial admin password:"
  log "-------------------------------------"
  ARGOCD_PASSWORD=$(kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath="{.data.password}" | base64 -d)
  log "${ARGOCD_PASSWORD}"
  log "-------------------------------------"
  log "Username: admin"
}

load_images() {
  local image missing=0
  for image in ${IMAGES}; do
    if docker image inspect "${image}" >/dev/null 2>&1; then
      log "Loading image '${image}' into Kind cluster..."
      kind load docker-image "${image}" --name "${KIND_CLUSTER_NAME}"
    else
      log "Pulling image '${image}' from registry..."
      docker pull "${image}"
      if [[ $? -eq 0 ]]; then
        log "Loading pulled image '${image}' into Kind cluster..."
        kind load docker-image "${image}" --name "${KIND_CLUSTER_NAME}"
      else
        log "Failed to pull image '${image}' from registry."
        missing=1
      fi
    fi
  done
  return "${missing}"
}

apply_manifests() {
  log "Applying ArgoCD Application manifest from ${ARGOCD_MANIFEST}..."
  kubectl apply -f "${ARGOCD_MANIFEST}"

  log "Applying ArgoCD ingress..."
  kubectl apply -f "${REPO_ROOT}/devops/argocd/argocd-ingress.yaml"

  log "Waiting for ArgoCD Application to sync..."
  kubectl wait --for=condition=available --timeout=600s application/pathway-submission -n argocd || log "Application sync timeout, check ArgoCD UI for status."

  log "ArgoCD Application synced. Checking pod status..."
  kubectl get pods -n agent-invest --no-headers | head -5 || log "Pods not ready yet, check with 'kubectl get pods -n agent-invest'"

  log "ArgoCD UI at http://localhost:8080 (admin/${ARGOCD_PASSWORD}) to monitor deployment progress."
}

main() {
  require kind
  require kubectl
  require docker
  require helm

  local cluster_created=1
  if create_cluster; then
    cluster_created=0
  fi

  if [[ "${cluster_created}" -eq 0 ]]; then
    install_ingress
    install_cert_manager
    install_argocd
    
    # Configure GitHub authentication for ArgoCD after ArgoCD is installed
    if [[ -f "${SCRIPT_DIR}/configure-github.sh" ]]; then
      log "Configuring GitHub authentication for ArgoCD..."
      bash "${SCRIPT_DIR}/configure-github.sh"
    else
      log "Warning: configure-github.sh not found, skipping GitHub configuration."
    fi
    
    # Create Kubernetes secrets after ArgoCD is configured
    if [[ -f "${SCRIPT_DIR}/create-secrets.sh" ]]; then
      log "Creating namespace 'agent-invest' if it doesn't exist..."
      kubectl create namespace agent-invest --dry-run=client -o yaml | kubectl apply -f - || true
      
      log "Creating Kubernetes secrets..."
      bash "${SCRIPT_DIR}/create-secrets.sh" || log "Warning: Some secrets may not have been created successfully"
    else
      log "Warning: create-secrets.sh not found, skipping secrets creation."
    fi
  else
    log "Ensuring ingress controller is present..."
    kubectl get ns ingress-nginx >/dev/null 2>&1 || install_ingress

    log "Ensuring cert-manager is present..."
    kubectl get ns cert-manager >/dev/null 2>&1 || install_cert_manager

    log "Ensuring ArgoCD is present..."
    kubectl get ns argocd >/dev/null 2>&1 || install_argocd
    
    # Configure GitHub authentication for ArgoCD after ArgoCD is installed
    if [[ -f "${SCRIPT_DIR}/configure-github.sh" ]]; then
      log "Configuring GitHub authentication for ArgoCD..."
      bash "${SCRIPT_DIR}/configure-github.sh"
    else
      log "Warning: configure-github.sh not found, skipping GitHub configuration."
    fi
    
    # Create Kubernetes secrets after ArgoCD is configured
    if [[ -f "${SCRIPT_DIR}/create-secrets.sh" ]]; then
      log "Creating namespace 'agent-invest' if it doesn't exist..."
      kubectl create namespace agent-invest --dry-run=client -o yaml | kubectl apply -f - || true
      
      log "Creating Kubernetes secrets..."
      bash "${SCRIPT_DIR}/create-secrets.sh" || log "Warning: Some secrets may not have been created successfully"
    else
      log "Warning: create-secrets.sh not found, skipping secrets creation."
    fi
  fi

  # Load images (don't fail if missing)
  load_images || log "Warning: Some images were not loaded. Build them locally or update IMAGES."
  
  # Always apply ArgoCD manifests
  apply_manifests

  log "Cluster '${KIND_CLUSTER_NAME}' is ready."
  log "ArgoCD UI: kubectl port-forward svc/argocd-server -n argocd 8080:80 (then visit http://localhost:8080)"
  log "ArgoCD UI (via ingress): https://argocd.localhost (admin/${ARGOCD_PASSWORD})"
  log "ArgoCD Admin Password: ${ARGOCD_PASSWORD}"
  log "Hosts to add to /etc/hosts: localhost argocd.localhost, agent-invest.local, api.agent-invest.local, grafana.agent-invest.local, prometheus.agent-invest.local, loki.agent-invest.local, flower.agent-invest.local"
}

main "$@"

