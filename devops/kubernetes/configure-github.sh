#!/usr/bin/env bash
# Helper script to configure ArgoCD with GitHub authentication
# This can be run separately or the credentials will be picked up by start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGOCD_MANIFEST="${ARGOCD_MANIFEST:-${SCRIPT_DIR}/../argocd/argocd.yml}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

# Check if GitHub token is provided via environment or .env file
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  # Try to load from .env file
  ENV_FILE="${SCRIPT_DIR}/../../.env"
  if [[ -f "${ENV_FILE}" ]]; then
    GITHUB_TOKEN=$(grep "^GITHUB_ACCESS_TOKEN=" "${ENV_FILE}" | cut -d'=' -f2- | sed 's/^"//' | sed 's/"$//')
  fi
  
  # If still not found, prompt user
  if [[ -z "${GITHUB_TOKEN}" ]]; then
    echo "GitHub Personal Access Token (PAT) required."
    echo ""
    echo "To create a GitHub PAT:"
    echo "1. Go to https://github.com/settings/profile"
    echo "2. Click 'Developer settings' in the left sidebar (scroll down)"
    echo "3. Click 'Personal access tokens' → 'Tokens (classic)'"
    echo "4. Click 'Generate new token' → 'Generate new token (classic)'"
    echo "5. Give it a name (e.g., 'ArgoCD')"
    echo "6. Select expiration (e.g., 90 days or No expiration)"
    echo "7. Select scopes: 'repo' (for private repos) or 'public_repo' (for public repos)"
    echo "8. Click 'Generate token' at the bottom"
    echo "9. Copy the token immediately (you won't see it again!)"
    echo ""
    read -sp "Enter your GitHub Personal Access Token: " GITHUB_TOKEN
    echo ""
    
    if [[ -z "${GITHUB_TOKEN}" ]]; then
      echo "Error: GitHub token is required"
      exit 1
    fi
  fi
fi

# Optionally get username
if [[ -z "${GITHUB_USERNAME:-}" ]]; then
  # Try to load from .env file or use default
  ENV_FILE="${SCRIPT_DIR}/../../.env"
  if [[ -f "${ENV_FILE}" ]]; then
    GITHUB_USERNAME=$(grep "^GITHUB_USERNAME=" "${ENV_FILE}" | cut -d'=' -f2- | sed 's/^"//' | sed 's/"$//' || echo "git")
  else
    GITHUB_USERNAME="git"
  fi
fi

export GITHUB_TOKEN
export GITHUB_USERNAME

log "Configuring ArgoCD with GitHub credentials..."

# Wait for ArgoCD to be ready
kubectl wait --namespace argocd \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/name=argocd-repo-server \
  --timeout=60s 2>/dev/null || {
  log "Warning: ArgoCD repo server not ready. GitHub config may fail."
}

# Extract repository URL from ArgoCD application
repo_url=$(kubectl get application pathway-submission -n argocd -o jsonpath='{.spec.source.repoURL}' 2>/dev/null || echo "")

if [[ -z "${repo_url}" ]]; then
  # Try to get it from the manifest file
  repo_url=$(grep -A 5 "source:" "${ARGOCD_MANIFEST}" | grep "repoURL:" | awk '{print $2}' | tr -d '"' || echo "")
fi

if [[ -z "${repo_url}" ]]; then
  log "Warning: Could not determine repository URL. Using default from argocd.yml"
  # Replace YOUR_GITHUB_USERNAME with your GitHub username
  repo_url="https://github.com/YOUR_GITHUB_USERNAME/Agentic-Trading-Platform-Pathway.git"
fi

log "Configuring repository: ${repo_url}"

# Determine if it's HTTPS or SSH
if [[ "${repo_url}" == https://* ]]; then
  # HTTPS authentication with token
  log "Using HTTPS authentication with username: ${GITHUB_USERNAME}"
  
  # Create repository secret for ArgoCD
  kubectl create secret generic github-repo-cred \
    --namespace argocd \
    --from-literal=type=git \
    --from-literal=url="${repo_url}" \
    --from-literal=password="${GITHUB_TOKEN}" \
    --from-literal=username="${GITHUB_USERNAME}" \
    --dry-run=client -o yaml | kubectl apply -f -
  
  # Label the secret so ArgoCD recognizes it
  kubectl label secret github-repo-cred -n argocd \
    argocd.argoproj.io/secret-type=repository \
    --overwrite
  
  log "GitHub repository secret created for HTTPS authentication."
  
elif [[ "${repo_url}" == git@* ]] || [[ "${repo_url}" == ssh://* ]]; then
  # SSH authentication
  log "SSH URL detected. For SSH authentication, you need to:"
  log "1. Create an SSH key pair"
  log "2. Add the public key to your GitHub account"
  log "3. Create a secret with the private key:"
  log "   kubectl create secret generic github-ssh-key \\"
  log "     --namespace argocd \\"
  log "     --from-file=sshPrivateKey=<path-to-private-key> \\"
  log "     --from-literal=type=git \\"
  log "     --from-literal=url=${repo_url}"
  log "   kubectl label secret github-ssh-key -n argocd argocd.argoproj.io/secret-type=repository"
  exit 0
else
  log "Warning: Unknown repository URL format: ${repo_url}"
  exit 1
fi

# Wait a moment for ArgoCD to pick up the secret
sleep 3

# Trigger a refresh of the application
log "Triggering ArgoCD application refresh..."
kubectl patch application pathway-submission -n argocd \
  --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || {
  log "Note: Application refresh triggered. ArgoCD will sync automatically."
}

log ""
log "Configuration complete!"
log "You can verify the configuration in ArgoCD UI:"
log "  kubectl port-forward svc/argocd-server -n argocd 8080:80"
log "  Then visit http://localhost:8080"
log "  Go to Settings > Repositories to see the configured repository"
log ""
log "ArgoCD should now be able to sync from your GitHub repository automatically."

