#!/bin/bash

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo -e "${RED}================================================${NC}"
    echo -e "${RED}  $1${NC}"
    echo -e "${RED}================================================${NC}"
    echo ""
}

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    print_error "kubectl is not installed. Please install kubectl first."
    exit 1
fi

print_header "🗑️  Agent-Invest Platform Destruction"

# Confirmation prompt
print_warning "This will DELETE all resources in the agent-invest namespace!"
print_warning "This action CANNOT be undone!"
echo ""
read -p "Are you sure you want to continue? (type 'yes' to confirm): " -r
echo
if [[ ! $REPLY = "yes" ]]; then
    print_info "Destruction cancelled"
    exit 0
fi

# Step 1: Delete ArgoCD Application (if exists)
print_header "🔄 Removing ArgoCD Application"
if kubectl get application pathway-submission -n argocd &> /dev/null; then
    print_info "Deleting ArgoCD Application..."
    kubectl delete -f ../argocd/argocd.yml || print_warning "Failed to delete ArgoCD Application"
    print_success "ArgoCD Application deleted"
else
    print_info "ArgoCD Application not found, skipping"
fi

# Step 2: Delete Ingress resources
print_header "🌐 Deleting Ingress Resources"
print_info "Removing Ingress configurations..."
kubectl delete -f ingress.yaml || print_warning "Failed to delete Ingress resources"
print_success "Ingress resources deleted"

# Step 3: Delete application deployments
print_header "🚀 Deleting Application Deployments"
print_info "Removing applications..."
kubectl delete -f apps.yaml || print_warning "Failed to delete applications"
print_success "Applications deleted"

# Step 4: Delete ConfigMaps
print_header "⚙️ Deleting ConfigMaps"
print_info "Removing ConfigMaps..."
kubectl delete -f configmaps.yaml || print_warning "Failed to delete ConfigMaps"
print_success "ConfigMaps deleted"

# Step 5: Delete Redis instances
print_header "📦 Deleting Redis Instances"
print_info "Removing Redis..."
kubectl delete -f redis.yaml || print_warning "Failed to delete Redis"
print_success "Redis instances deleted"

# Step 6: Delete PostgreSQL databases
print_header "🗄️ Deleting PostgreSQL Databases"
print_info "Removing PostgreSQL..."
kubectl delete -f postgres.yaml || print_warning "Failed to delete PostgreSQL"
print_success "PostgreSQL databases deleted"

# Step 7: Delete secrets
print_header "🔑 Deleting Secrets"
print_info "Removing secrets..."
kubectl delete secret auth-db-credentials -n agent-invest || print_warning "auth-db-credentials not found"
kubectl delete secret portfolio-db-credentials -n agent-invest || print_warning "portfolio-db-credentials not found"
kubectl delete secret auth-env-secret -n agent-invest || print_warning "auth-env-secret not found"
kubectl delete secret portfolio-env-secret -n agent-invest || print_warning "portfolio-env-secret not found"
print_success "Secrets deleted"

# Step 8: Delete PersistentVolumeClaims
print_header "💾 Deleting PersistentVolumeClaims"
print_info "Removing PVCs..."
kubectl delete pvc -l app=auth-postgres -n agent-invest || print_warning "No auth-postgres PVCs found"
kubectl delete pvc -l app=portfolio-postgres -n agent-invest || print_warning "No portfolio-postgres PVCs found"
kubectl delete pvc -l app=auth-redis -n agent-invest || print_warning "No auth-redis PVCs found"
kubectl delete pvc -l app=portfolio-redis -n agent-invest || print_warning "No portfolio-redis PVCs found"
print_success "PVCs deleted"

# Step 9: Delete cert-manager ClusterIssuers
print_header "🔐 Deleting Certificate Issuers"
print_info "Removing ClusterIssuers..."
kubectl delete -f cert-manager.yaml || print_warning "Failed to delete ClusterIssuers"
print_success "ClusterIssuers deleted"

# Step 10: Delete namespace
print_header "📁 Deleting Namespace"
print_info "Removing agent-invest namespace..."
kubectl delete -f namespace.yaml || print_warning "Failed to delete namespace"
print_info "Waiting for namespace to be fully removed..."
kubectl wait --for=delete namespace/agent-invest --timeout=120s || print_warning "Namespace deletion timeout"
print_success "Namespace deleted"

# Optional: Uninstall ArgoCD
print_header "🔄 Uninstall ArgoCD"
read -p "Do you want to uninstall ArgoCD? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Uninstalling ArgoCD..."
    kubectl delete -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml || print_warning "Failed to uninstall ArgoCD"
    kubectl delete namespace argocd || print_warning "Failed to delete argocd namespace"
    print_success "ArgoCD uninstalled"
fi

# Optional: Uninstall NGINX Ingress Controller
print_header "🌐 Uninstall NGINX Ingress Controller"
read -p "Do you want to uninstall NGINX Ingress Controller? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Uninstalling NGINX Ingress Controller..."
    helm uninstall ingress-nginx -n ingress-nginx || print_warning "Failed to uninstall ingress-nginx"
    kubectl delete namespace ingress-nginx || print_warning "Failed to delete ingress-nginx namespace"
    print_success "NGINX Ingress Controller uninstalled"
fi

# Optional: Uninstall cert-manager
print_header "📜 Uninstall cert-manager"
read -p "Do you want to uninstall cert-manager? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Uninstalling cert-manager..."
    kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.2/cert-manager.yaml || print_warning "Failed to uninstall cert-manager"
    print_success "cert-manager uninstalled"
fi

# Optional: Delete Kind cluster
print_header "🐳 Delete Kind Cluster"
read -p "Do you want to delete the Kind cluster 'agent-invest'? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Deleting Kind cluster 'agent-invest'..."
    kind delete cluster --name agent-invest || print_warning "Failed to delete Kind cluster"
    print_success "Kind cluster deleted"
fi

# Step 11: Display final status
print_header "✅ Destruction Complete!"
echo ""
print_success "Agent-Invest Platform has been destroyed successfully!"
echo ""
print_info "Remaining resources (if any):"
kubectl get all -n agent-invest 2>/dev/null || print_info "No resources found in agent-invest namespace"
echo ""
print_warning "Note: PersistentVolumes may still exist and need manual cleanup"
print_info "To list PersistentVolumes: kubectl get pv"
print_info "To delete a PV: kubectl delete pv <pv-name>"
echo ""
