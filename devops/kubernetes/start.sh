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
IMAGES="${IMAGES:-punhaniabhishek/agent-invest-frontend:latest punhaniabhishek/agent-invest-auth-server:latest punhaniabhishek/agent-invest-portfolio-server:latest}"
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

  log "ArgoCD Application created. ArgoCD will now deploy your Kubernetes manifests."
  log "Check ArgoCD UI at http://localhost:8080 (admin/${ARGOCD_PASSWORD}) to monitor deployment progress."

  log "Waiting for ArgoCD to sync the application..."
  local max_attempts=60
  local attempt=0
  local sync_status=""
  local operation_phase=""
  
  while [[ ${attempt} -lt ${max_attempts} ]]; do
    sync_status=$(kubectl get application pathway-submission -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "")
    operation_phase=$(kubectl get application pathway-submission -n argocd -o jsonpath='{.status.operationState.phase}' 2>/dev/null || echo "")
    
    # Check if sync is complete and successful
    if [[ "${sync_status}" == "Synced" ]]; then
      log "ArgoCD application synced successfully."
      break
    fi
    
    # Check if there's an error
    local error_msg=$(kubectl get application pathway-submission -n argocd -o jsonpath='{.status.conditions[?(@.type=="SyncError")].message}' 2>/dev/null || echo "")
    if [[ -n "${error_msg}" ]] && [[ "${operation_phase}" != "Running" ]]; then
      log "ArgoCD sync error: ${error_msg}"
      log "Check ArgoCD UI for details: kubectl port-forward svc/argocd-server -n argocd 8080:80"
      break
    fi
    
    # Show progress
    if [[ "${operation_phase}" == "Running" ]]; then
      log "ArgoCD sync in progress... (attempt $((attempt + 1))/${max_attempts})"
    else
      log "Waiting for ArgoCD sync... Status: ${sync_status:-Unknown} (attempt $((attempt + 1))/${max_attempts})"
    fi
    
    sleep 5
    attempt=$((attempt + 1))
  done

  if [[ ${attempt} -eq ${max_attempts} ]]; then
    log "Warning: ArgoCD sync timeout after $((max_attempts * 5)) seconds."
    log "Current status:"
    kubectl get application pathway-submission -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null && echo ""
    log "Check ArgoCD UI for details: kubectl port-forward svc/argocd-server -n argocd 8080:80"
  fi

  log "Waiting for namespace 'agent-invest' to be created..."
  local ns_attempt=0
  while [[ ${ns_attempt} -lt 20 ]]; do
    if kubectl get namespace agent-invest >/dev/null 2>&1; then
      log "Namespace 'agent-invest' exists."
      break
    fi
    log "Waiting for namespace creation... (attempt $((ns_attempt + 1))/20)"
    sleep 2
    ns_attempt=$((ns_attempt + 1))
  done

  if ! kubectl get namespace agent-invest >/dev/null 2>&1; then
    log "Warning: Namespace 'agent-invest' not found. ArgoCD may still be syncing."
    return 0
  fi

  log "Waiting for workloads in namespace 'agent-invest' to become ready..."
  if kubectl wait --namespace agent-invest \
    --for=condition=Available deployment --all \
    --timeout=300s 2>/dev/null; then
    log "All deployments are ready."
  else
    log "Warning: Some deployments may not be ready yet. Check ArgoCD UI for details."
    log "Current deployments status:"
    kubectl get deployments -n agent-invest 2>/dev/null || true
  fi
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
  else
    log "Ensuring ingress controller is present..."
    kubectl get ns ingress-nginx >/dev/null 2>&1 || install_ingress

    log "Ensuring cert-manager is present..."
    kubectl get ns cert-manager >/dev/null 2>&1 || install_cert_manager

    log "Ensuring ArgoCD is present..."
    kubectl get ns argocd >/dev/null 2>&1 || install_argocd
  fi

  load_images || log "One or more images were not loaded. Build them locally or update IMAGES."
  apply_manifests

  log "Cluster '${KIND_CLUSTER_NAME}' is ready."
  log "ArgoCD UI: kubectl port-forward svc/argocd-server -n argocd 8080:80 (then visit http://localhost:8080)"
  log "ArgoCD Admin Password: ${ARGOCD_PASSWORD}"
  log "Hosts to add to /etc/hosts: agent-invest.local, api.agent-invest.local, grafana.agent-invest.local, prometheus.agent-invest.local, loki.agent-invest.local, flower.agent-invest.local"
}

main "$@"

