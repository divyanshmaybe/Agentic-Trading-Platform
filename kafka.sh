#!/usr/bin/env bash

set -euo pipefail

# Use Apache Kafka official image with KRaft mode
IMAGE="${KAFKA_IMAGE:-apache/kafka:3.8.0}"
CONTAINER_NAME="${KAFKA_CONTAINER_NAME:-pathway-kafka}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to launch Kafka" >&2
  exit 1
fi

echo "Pulling Kafka image ${IMAGE}..."
docker pull "${IMAGE}" >/dev/null

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Removing existing container ${CONTAINER_NAME}..."
  docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

echo "Starting Kafka container ${CONTAINER_NAME} (KRaft, no ZooKeeper)..."
docker run -d --name "${CONTAINER_NAME}" \
  -p 9092:9092 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
  -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=true \
  -e CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk \
  "${IMAGE}" >/dev/null

echo "Kafka is starting up. Use 'docker logs -f ${CONTAINER_NAME}' to monitor readiness."
