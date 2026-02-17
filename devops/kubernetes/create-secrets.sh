#!/bin/bash

# Script to create Kubernetes secrets from .env files
# This ensures all sensitive environment variables are properly injected as secrets

set -e

NAMESPACE="${NAMESPACE:-agent-invest}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "🔐 Creating Kubernetes secrets from environment files..."
echo "📁 Root directory: $ROOT_DIR"
echo "🎯 Namespace: $NAMESPACE"
echo ""

# Function to load .env file and create secret
load_env_file() {
    local env_file="$1"
    if [ ! -f "$env_file" ]; then
        echo "⚠️  Warning: $env_file not found, skipping..."
        return 1
    fi
    
    echo "📄 Loading: $env_file"
    # Export all variables from .env file (excluding comments and empty lines)
    set -a
    source <(grep -v '^#' "$env_file" | grep -v '^$' | sed 's/\r$//')
    set +a
    return 0
}

# Function to check if variable is set and not empty
check_var() {
    local var_name="$1"
    local var_value="${!var_name}"
    if [ -z "$var_value" ]; then
        echo "  ⚠️  $var_name is not set or empty"
        return 1
    else
        echo "  ✓ $var_name is set"
        return 0
    fi
}

# Load root .env
echo ""
if ! load_env_file "$ROOT_DIR/.env"; then
    echo "❌ Error: Root .env file not found at $ROOT_DIR/.env"
    echo "Please create .env file with required variables"
    exit 1
fi

# Load portfolio-server .env
echo ""
if ! load_env_file "$ROOT_DIR/apps/portfolio-server/.env"; then
    echo "❌ Error: Portfolio server .env file not found at $ROOT_DIR/apps/portfolio-server/.env"
    echo "Please create .env file with required variables"
    exit 1
fi

# Validate required variables
echo ""
echo "🔍 Validating required environment variables..."
echo ""
echo "Auth Server Variables:"
check_var "JWT_SECRET_EMAIL"
check_var "JWT_SECRET_PASSWORD"
check_var "JWT_SECRET_ACCESS"
check_var "JWT_SECRET_REFRESH"
check_var "SENDER_EMAIL_ADDRESS"
check_var "SENDGRID_API_KEY"
check_var "INTERNAL_SERVICE_SECRET"

echo ""
echo "Portfolio Server Variables:"
check_var "GEMINI_API_KEY"
check_var "NEWS_ORG_API_KEY"
check_var "SERP_API_KEY"
check_var "ANGELONE_CLIENT_CODE"
check_var "ANGELONE_API_KEY"
check_var "ANGELONE_PASSWORD"
check_var "ANGELONE_TOTP_SECRET"

# Optional variables (don't fail if missing)
if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "  ✓ OPENAI_API_KEY is set (optional)"
else
    echo "  ⚠️  OPENAI_API_KEY is not set (optional)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Creating Secrets in Kubernetes..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create or update auth-env-secret
echo ""
echo "🔑 Creating auth-env-secret..."
kubectl create secret generic auth-env-secret \
  --namespace="$NAMESPACE" \
  --from-literal=DATABASE_URL="postgresql://auth_user:auth_password@auth-postgres:5432/auth_db" \
  --from-literal=JWT_SECRET_EMAIL="${JWT_SECRET_EMAIL}" \
  --from-literal=JWT_SECRET_PASSWORD="${JWT_SECRET_PASSWORD}" \
  --from-literal=JWT_SECRET_ACCESS="${JWT_SECRET_ACCESS}" \
  --from-literal=JWT_SECRET_REFRESH="${JWT_SECRET_REFRESH}" \
  --from-literal=SENDER_EMAIL_ADDRESS="${SENDER_EMAIL_ADDRESS}" \
  --from-literal=SENDGRID_API_KEY="${SENDGRID_API_KEY}" \
  --from-literal=INTERNAL_SERVICE_SECRET="${INTERNAL_SERVICE_SECRET}" \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "  ✓ auth-env-secret created/updated (8 keys)"
else
    echo "  ✗ Failed to create auth-env-secret"
    exit 1
fi

# Create or update portfolio-env-secret
echo ""
echo "🔑 Creating portfolio-env-secret..."
kubectl create secret generic portfolio-env-secret \
  --namespace="$NAMESPACE" \
  --from-literal=DATABASE_URL="postgresql://portfolio_user:portfolio_password@portfolio-postgres:5432/portfolio_db" \
  --from-literal=SHADOW_DATABASE_URL="postgresql://portfolio_user:portfolio_password@portfolio-postgres:5432/portfolio_db" \
  --from-literal=CELERY_BROKER_URL="redis://portfolio-redis:6379/0" \
  --from-literal=CELERY_RESULT_BACKEND="redis://portfolio-redis:6379/1" \
  --from-literal=INTERNAL_SERVICE_SECRET="${INTERNAL_SERVICE_SECRET}" \
  --from-literal=GEMINI_API_KEY="${GEMINI_API_KEY}" \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}" \
  --from-literal=NEWS_ORG_API_KEY="${NEWS_ORG_API_KEY}" \
  --from-literal=SERP_API_KEY="${SERP_API_KEY}" \
  --from-literal=ANGELONE_CLIENT_CODE="${ANGELONE_CLIENT_CODE}" \
  --from-literal=ANGELONE_API_KEY="${ANGELONE_API_KEY}" \
  --from-literal=ANGELONE_PASSWORD="${ANGELONE_PASSWORD}" \
  --from-literal=ANGELONE_TOTP_SECRET="${ANGELONE_TOTP_SECRET}" \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "  ✓ portfolio-env-secret created/updated (14 keys)"
else
    echo "  ✗ Failed to create portfolio-env-secret"
    exit 1
fi

# Create or update database credentials
echo ""
echo "🔑 Creating auth-db-credentials..."
kubectl create secret generic auth-db-credentials \
  --namespace="$NAMESPACE" \
  --from-literal=POSTGRES_USER=auth_user \
  --from-literal=POSTGRES_PASSWORD=auth_password \
  --from-literal=POSTGRES_DB=auth_db \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "  ✓ auth-db-credentials created/updated (3 keys)"
else
    echo "  ✗ Failed to create auth-db-credentials"
    exit 1
fi

echo ""
echo "🔑 Creating portfolio-db-credentials..."
kubectl create secret generic portfolio-db-credentials \
  --namespace="$NAMESPACE" \
  --from-literal=POSTGRES_USER=portfolio_user \
  --from-literal=POSTGRES_PASSWORD=portfolio_password \
  --from-literal=POSTGRES_DB=portfolio_db \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "  ✓ portfolio-db-credentials created/updated (3 keys)"
else
    echo "  ✗ Failed to create portfolio-db-credentials"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All secrets created successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 Secrets Summary:"
echo "  - auth-env-secret: 8 environment variables"
echo "  - portfolio-env-secret: 14 environment variables"
echo "  - auth-db-credentials: PostgreSQL credentials"
echo "  - portfolio-db-credentials: PostgreSQL credentials"
echo ""
echo "🔍 To verify secrets (without exposing values):"
echo "  kubectl get secrets -n $NAMESPACE"
echo ""
echo "� Service URLs (from ConfigMaps):"
echo "  - auth-postgres:5432 (PostgreSQL for auth)"
echo "  - portfolio-postgres:5432 (PostgreSQL for portfolio)"
echo "  - auth-redis:6379 (Redis for auth sessions)"
echo "  - portfolio-redis:6379 (Redis for Celery)"
echo "  - auth-server:4000 (Auth API)"
echo "  - portfolio-server:8000 (Portfolio API)"
echo ""
echo "⚠️  Security Note:"
echo "  - Secret values are NOT displayed for security"
echo "  - Never commit .env files to version control"
echo "  - Use 'kubectl get secret <name> -n $NAMESPACE -o jsonpath=\"{.data}\"' to view encoded secrets"
echo ""
