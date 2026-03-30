#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
IMAGE_NAMESPACE="${IMAGE_NAMESPACE:?missing IMAGE_NAMESPACE}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"

if [[ ! -f "${APP_DIR}/${COMPOSE_FILE}" ]]; then
  echo "Compose de produção não encontrado: ${APP_DIR}/${COMPOSE_FILE}" >&2
  exit 1
fi

wait_for_http() {
  local url="$1"
  local label="$2"

  for _ in $(seq 1 30); do
    if curl --fail --silent "$url" >/dev/null; then
      echo "OK: ${label}"
      return 0
    fi
    sleep 2
  done

  echo "Falha ao validar ${label}: ${url}" >&2
  return 1
}

if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
fi

cd "${APP_DIR}"
export IMAGE_NAMESPACE IMAGE_TAG

if [[ "${SKIP_GIT_PULL}" != "1" ]]; then
  git diff --quiet
  git pull --ff-only origin main
fi

docker compose -f "${COMPOSE_FILE}" pull
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans

wait_for_http "http://127.0.0.1:8000/health" "backend Hughie"
wait_for_http "http://127.0.0.1:47831/v1/health" "broker"
wait_for_http "http://127.0.0.1:3000" "frontend"

docker compose -f "${COMPOSE_FILE}" ps
