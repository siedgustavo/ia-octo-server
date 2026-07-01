#!/usr/bin/env bash
set -euo pipefail

TARGET_HOSTNAME="${TARGET_HOSTNAME:-aiworker.core.sied.ar}"
INSTALL_DIR="${INSTALL_DIR:-/opt/llamacpp-rpc/server}"
MODELS_DIR="${MODELS_DIR:-/opt/llamacpp-rpc/models}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
  fi
}

install_docker_almalinux() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    systemctl enable --now docker
    return
  fi

  dnf install -y dnf-plugins-core ca-certificates curl
  dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

require_root

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
else
  echo "Cannot detect OS: /etc/os-release is missing." >&2
  exit 1
fi

if [[ "${ID}" != "almalinux" && "${ID_LIKE:-}" != *"rhel"* && "${ID_LIKE:-}" != *"fedora"* ]]; then
  echo "This POC setup script targets Alma/RHEL-like hosts. Detected ID=${ID}." >&2
  exit 1
fi

hostnamectl set-hostname "${TARGET_HOSTNAME}"
install_docker_almalinux

mkdir -p "${INSTALL_DIR}" "${MODELS_DIR}"
install -m 0644 "${SCRIPT_DIR}/Dockerfile" "${INSTALL_DIR}/Dockerfile"
install -m 0644 "${SCRIPT_DIR}/docker-compose.yml" "${INSTALL_DIR}/docker-compose.yml"
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  install -m 0644 "${SCRIPT_DIR}/.env.example" "${INSTALL_DIR}/.env"
fi

cat <<EOF
Nodo 1 listo.

Hostname: ${TARGET_HOSTNAME}
Compose dir: ${INSTALL_DIR}
Modelos: ${MODELS_DIR}

Edita ${INSTALL_DIR}/.env y apunta MODEL_PATH a un GGUF existente dentro de /models.
Luego:

  cd ${INSTALL_DIR}
  docker compose up --build -d
  docker compose logs -f llama-server
EOF
