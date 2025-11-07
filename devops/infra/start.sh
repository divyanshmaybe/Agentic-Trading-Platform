#!/bin/bash

# Initialize and apply Terraform
terraform init
terraform plan

terraform apply -auto-approve

export KUBECONFIG=./kubeconfig

# Helm repos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add stevehipwell https://stevehipwell.github.io/helm-charts/
helm repo update

# Label + annotate Thanos secret for Helm ownership (required)
kubectl label secret thanos-objstore-config app.kubernetes.io/managed-by=Helm --overwrite -n monitoring
kubectl annotate secret thanos-objstore-config meta.helm.sh/release-name=thanos --overwrite -n monitoring
kubectl annotate secret thanos-objstore-config meta.helm.sh/release-namespace=monitoring --overwrite -n monitoring

# Install kube-prometheus-stack with Thanos sidecar
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version 78.5.0 \
  --set grafana.service.type=ClusterIP \
  --set grafana.persistence.enabled=true \
  --set grafana.persistence.size=10Gi \
  --set prometheus.service.type=ClusterIP \
  --set prometheus.prometheusSpec.retention=15d \
  --set prometheus.prometheusSpec.disableCompaction=true \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.accessModes[0]=ReadWriteOnce \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=10Gi \
  --set prometheus.prometheusSpec.thanos.image="quay.io/thanos/thanos:v0.39.2" \
  --set prometheus.prometheusSpec.thanos.objectStorageConfig.existingSecret.name=thanos-objstore-config \
  --set prometheus.prometheusSpec.thanos.objectStorageConfig.existingSecret.key=objstore.yml \
  --set prometheus.prometheusSpec.servicePerReplica=true \
  --set prometheus.thanosService.enabled=true \
  --set prometheus.thanosServiceMonitor.enabled=true \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set-json prometheus.prometheusSpec.serviceMonitorNamespaceSelector='{}' \
  --set prometheus.prometheusSpec.externalLabels.cluster="terraform-k8s" \
  --set prometheus.prometheusSpec.replicaExternalLabelName="prometheus_replica" \
  --set alertmanager.service.type=ClusterIP \
  --set kubeApiServer.enabled=true \
  --set kubelet.enabled=true \
  --set kubeControllerManager.enabled=true \
  --set kubeScheduler.enabled=true \
  --set kubeStateMetrics.enabled=true \
  --set nodeExporter.enabled=true \
  --set prometheusOperator.enabled=true

# Install Thanos components
helm upgrade --install thanos stevehipwell/thanos \
  --namespace monitoring \
  --create-namespace \
  --set image.repository=quay.io/thanos/thanos \
  --set image.tag=v0.39.2 \
  --set objstoreConfig.type=secret \
  --set objstoreConfig.secretName=thanos-objstore-config \
  --set query.enabled=true \
  --set query.replicaCount=1 \
  --set query.service.type=ClusterIP \
  --set query.service.ports.http=9090 \
  --set query.replicaLabel=prometheus_replica \
  --set-json 'additionalEndpoints=["dnssrv+_grpc._tcp.kube-prometheus-stack-thanos-discovery.monitoring.svc.cluster.local"]' \
  --set queryFrontend.enabled=true \
  --set queryFrontend.service.type=ClusterIP \
  --set storegateway.enabled=true \
  --set storegateway.replicaCount=1 \
  --set storegateway.persistence.enabled=true \
  --set storegateway.persistence.size=10Gi \
  --set compactor.enabled=true \
  --set compactor.retentionResolutionRaw=15d \
  --set compactor.retentionResolution5m=30d \
  --set compactor.retentionResolution1h=90d \
  --set compactor.persistence.enabled=true \
  --set compactor.persistence.size=10Gi \
  --set ruler.enabled=true \
  --set ruler.replicaCount=1 \
  --set ruler.persistence.enabled=true \
  --set ruler.persistence.size=5Gi \
  --set receiver.enabled=true \
  --set receiver.replicaCount=1 \
  --set receiver.service.type=ClusterIP \
  --set metrics.enabled=true

# ServiceMonitor will be applied by ArgoCD from app directory

kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-server -n argocd --timeout=300s

# Apply ArgoCD custom configuration
echo "Applying ArgoCD configuration..."
kubectl apply -n argocd -f ../argocd/argocd.yml

# Flush DNS cache
sudo systemd-resolve --flush-caches
sudo resolvectl flush-caches

# it is a known issue that dns is not updated, try using cloudflare dns servers or restart the machine