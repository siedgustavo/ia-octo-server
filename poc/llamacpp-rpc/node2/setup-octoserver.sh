#!/usr/bin/env bash
set -euo pipefail

TARGET_HOSTNAME="${TARGET_HOSTNAME:-octoserver.core.sied.ar}"
STACK_DIR="${STACK_DIR:-/opt/ia-octo-server}"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
  fi
}

require_root

hostnamectl set-hostname "${TARGET_HOSTNAME}"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y dnf-plugins-core ca-certificates curl
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y ca-certificates curl docker.io docker-compose-plugin
  else
    echo "Cannot install Docker automatically on this OS." >&2
    exit 1
  fi
fi

systemctl enable --now docker
systemctl disable --now llama-rpc@0 llama-rpc@1 llama-rpc@2 llama-rpc@3 2>/dev/null || true
systemctl disable --now octofan-poc-safety.service 2>/dev/null || true

cd "${STACK_DIR}"
docker compose pull
docker compose up -d --remove-orphans

cat <<EOF
Octoserver RPC bridge listo.

Hostname: ${TARGET_HOSTNAME}
Stack dir: ${STACK_DIR}
RPC: ${TARGET_HOSTNAME}:5000,5001,5002,5003

Verificar:
  cd ${STACK_DIR}
  docker compose ps
  docker compose logs -f llamacpp-rpc-gpu0
EOF
