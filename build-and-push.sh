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
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}================================================${NC}"
    echo ""
}

# Configuration
# Set DOCKERHUB_USERNAME environment variable to your DockerHub username
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-your-dockerhub-username}"
PROJECT_NAME="agent-invest"
TAG="${TAG:-latest}"

print_header "🐳 Building and Pushing Docker Images to Docker Hub"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if logged in to Docker Hub
if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running or you don't have permissions."
    exit 1
fi

# Check Docker Hub login
if ! docker system info | grep -q "Username:"; then
    print_warning "Not logged in to Docker Hub. Please run: docker login"
    print_info "Or set DOCKERHUB_USERNAME environment variable"
    exit 1
fi

print_info "Docker Hub Username: $DOCKERHUB_USERNAME"
print_info "Project: $PROJECT_NAME"
print_info "Tag: $TAG"

# Function to build and push image
build_and_push() {
    local service_name="$1"
    local dockerfile_path="$2"
    local image_name="$DOCKERHUB_USERNAME/$PROJECT_NAME-$service_name:$TAG"

    print_info "Building $service_name..."
    # Build from project root with correct context
    docker build -f "$dockerfile_path/Dockerfile" -t "$image_name" .

    print_info "Pushing $image_name..."
    docker push "$image_name"

    print_success "$service_name pushed as $image_name"
}

# Build and push auth-server
print_header "🔐 Building Auth Server"
build_and_push "auth-server" "apps/auth_server"

# Build and push portfolio-server
print_header "📊 Building Portfolio Server"
build_and_push "portfolio-server" "apps/portfolio-server"

# Build and push frontend
print_header "🌐 Building Frontend"
build_and_push "frontend" "apps/frontend"

# Build and push notification-server
print_header "🔔 Building Notification Server"
build_and_push "notification-server" "apps/notification_server"

print_header "✅ All Images Built and Pushed!"
echo ""
print_success "Images pushed to Docker Hub:"
echo "  $DOCKERHUB_USERNAME/$PROJECT_NAME-auth-server:$TAG"
echo "  $DOCKERHUB_USERNAME/$PROJECT_NAME-portfolio-server:$TAG"
echo "  $DOCKERHUB_USERNAME/$PROJECT_NAME-frontend:$TAG"
echo "  $DOCKERHUB_USERNAME/$PROJECT_NAME-notification-server:$TAG"
echo ""
print_info "Update your Kubernetes manifests to use these images:"
echo "  image: $DOCKERHUB_USERNAME/$PROJECT_NAME-auth-server:$TAG"
echo "  image: $DOCKERHUB_USERNAME/$PROJECT_NAME-portfolio-server:$TAG"
echo "  image: $DOCKERHUB_USERNAME/$PROJECT_NAME-frontend:$TAG"
echo "  image: $DOCKERHUB_USERNAME/$PROJECT_NAME-notification-server:$TAG"
echo ""
print_info "To deploy with these images:"
echo "  cd devops/kubernetes"
echo "  ./start.sh"
echo ""
print_warning "Don't forget to update the imagePullPolicy if needed!"
