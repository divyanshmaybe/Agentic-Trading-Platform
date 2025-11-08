#!/usr/bin/env bash

set -euo pipefail

CHANNEL=""
BROKER="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
FROM_BEGINNING=0

usage() {
  cat <<EOF
Usage: $0 --channel <topic> [--broker <host:port>] [--from-beginning]

Consumes messages from the given Kafka topic using kcat.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --channel|-c)
      CHANNEL="${2:-}"
      shift 2
      ;;
    --broker|-b)
      BROKER="${2:-}"
      shift 2
      ;;
    --from-beginning)
      FROM_BEGINNING=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${CHANNEL}" ]]; then
  echo "Error: --channel is required" >&2
  usage
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to run the subscriber" >&2
  exit 1
fi

CMD=(kcat -b "${BROKER}" -t "${CHANNEL}" -C)
if [[ ${FROM_BEGINNING} -eq 1 ]]; then
  CMD+=(-o beginning)
else
  CMD+=(-o end)
fi

echo "Consuming topic '${CHANNEL}' from broker '${BROKER}'..."
echo "Press Ctrl+C to stop..."
echo "Waiting for messages (topic will be auto-created when publisher sends first message)..."
docker run --rm -it --network host edenhill/kcat:1.7.1 "${CMD[@]}"
