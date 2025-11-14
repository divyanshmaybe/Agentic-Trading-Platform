#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-agent-invest}"
KIND_CONFIG="${KIND_CONFIG:-${SCRIPT_DIR}/kind-config.yaml}"
INGRESS_MANIFEST="${INGRESS_MANIFEST:-https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml}"
CERT_MANAGER_MANIFEST="${CERT_MANAGER_MANIFEST:-https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml}"
KUSTOMIZE_DIR="${KUSTOMIZE_DIR:-${SCRIPT_DIR}}"
IMAGES="${IMAGES:-frontend_web:latest auth_server:latest portfolio_server:latest}"

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

load_images() {
  local image missing=0
  for image in ${IMAGES}; do
    if docker image inspect "${image}" >/dev/null 2>&1; then
      log "Loading image '${image}' into Kind cluster..."
      kind load docker-image "${image}" --name "${KIND_CLUSTER_NAME}"
    else
      log "Skipping image '${image}' (not found locally)."
      missing=1
    fi
  done
  return "${missing}"
}

apply_manifests() {
  log "Applying Kubernetes manifests from ${KUSTOMIZE_DIR}..."
  kubectl apply -k "${KUSTOMIZE_DIR}"

  log "Waiting for workloads in namespace 'agent-invest' to become ready..."
  kubectl wait --namespace agent-invest \
    --for=condition=Available deployment --all \
    --timeout=300s
}

main() {
  require kind
  require kubectl
  require docker

  local cluster_created=1
  if create_cluster; then
    cluster_created=0
  fi

  if [[ "${cluster_created}" -eq 0 ]]; then
    install_ingress
    install_cert_manager
  else
    log "Ensuring ingress controller is present..."
    kubectl get ns ingress-nginx >/dev/null 2>&1 || install_ingress

    log "Ensuring cert-manager is present..."
    kubectl get ns cert-manager >/dev/null 2>&1 || install_cert_manager
  fi

  load_images || log "One or more images were not loaded. Build them locally or update IMAGES."
  apply_manifests

  log "Cluster '${KIND_CLUSTER_NAME}' is ready."
  log "Hosts to add to /etc/hosts: localhost, api.localhost, grafana.localhost, prometheus.localhost, loki.localhost"
}

main "$@"

