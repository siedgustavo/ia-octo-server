#!/usr/bin/env bash
set -euo pipefail

TARGET_HOSTNAME="${TARGET_HOSTNAME:-gpubridge.core.sied.ar}"
LLAMA_CPP_REF="${LLAMA_CPP_REF:-master}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/llama.cpp-rpc}"
LLAMA_DIR="${INSTALL_ROOT}/llama.cpp"
BUILD_DIR="${LLAMA_DIR}/build-rpc-cuda"
RPC_SYMLINK="${INSTALL_ROOT}/current-rpc-server"
OCTOFAN_DIR="${OCTOFAN_DIR:-/opt/ia-octo-server}"
FAN_CLI="${FAN_CLI:-${OCTOFAN_DIR}/reference/octofan-hiveos-originals/fan_controller_cli}"
FAN_PWM="${FAN_PWM:-26}"

export PATH="/usr/local/cuda/bin:/usr/local/cuda-13.3/bin:/usr/local/cuda-13.2/bin:/usr/local/cuda-13.1/bin:/usr/local/cuda-13.0/bin:${PATH}"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
  fi
}

install_build_deps() {
  dnf install -y \
    ca-certificates \
    cmake \
    gcc \
    gcc-c++ \
    git \
    make \
    openssl-devel \
    which
}

install_cuda_if_needed() {
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1 && command -v nvcc >/dev/null 2>&1; then
    echo "nvidia-smi and nvcc work; keeping current NVIDIA driver/CUDA toolkit."
    return
  fi

  echo "Installing missing NVIDIA/CUDA components for Alma/RHEL-like host."
  local repo_major="${VERSION_ID%%.*}"
  dnf install -y dnf-plugins-core epel-release || true
  dnf config-manager --add-repo "https://developer.download.nvidia.com/compute/cuda/repos/rhel${repo_major}/x86_64/cuda-rhel${repo_major}.repo" \
    || dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel9/x86_64/cuda-rhel9.repo
  dnf clean expire-cache
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    dnf install -y cuda-toolkit
  else
    dnf install -y cuda-toolkit nvidia-driver-cuda nvidia-driver-cuda-libs
  fi
}

force_fans_low() {
  if [[ ! -x "${FAN_CLI}" ]]; then
    echo "Fan CLI not found at ${FAN_CLI}; skipping PWM safety step." >&2
    return
  fi

  echo "Forcing Octofan PWM ${FAN_PWM} before stopping Docker stack."
  for id in 0 1 2 3 4 5 6 7 8 9 10 11; do
    "${FAN_CLI}" -f "${id}" -v "${FAN_PWM}" || true
  done
}

stop_existing_docker_stack() {
  if [[ -f "${OCTOFAN_DIR}/docker-compose.yml" ]] && command -v docker >/dev/null 2>&1; then
    echo "Stopping current Octofan Docker stack at ${OCTOFAN_DIR}."
    (cd "${OCTOFAN_DIR}" && docker compose down) || true
  fi

  if systemctl list-unit-files docker.service >/dev/null 2>&1; then
    echo "Disabling Docker temporarily for RPC POC."
    systemctl disable --now docker || true
  fi
}

install_octofan_safety_service() {
  if [[ ! -x "${FAN_CLI}" ]]; then
    echo "Fan CLI not found at ${FAN_CLI}; skipping native Octofan safety service." >&2
    return
  fi

  install -d -m 0755 "${INSTALL_ROOT}/bin"
  cat > "${INSTALL_ROOT}/bin/octofan-safety-loop" <<EOF
#!/usr/bin/env bash
set -euo pipefail

FAN_CLI="${FAN_CLI}"
FAN_PWM="${FAN_PWM}"
last_pwm_apply=0

while true; do
  "\${FAN_CLI}" -s || true
  now="\$(date +%s)"
  if (( now - last_pwm_apply >= 30 )); then
    for id in 0 1 2 3 4 5 6 7 8 9 10 11; do
      "\${FAN_CLI}" -f "\${id}" -v "\${FAN_PWM}" || true
    done
    last_pwm_apply="\${now}"
  fi
  sleep 5
done
EOF
  chmod 0755 "${INSTALL_ROOT}/bin/octofan-safety-loop"

  cat > /etc/systemd/system/octofan-poc-safety.service <<'EOF'
[Unit]
Description=Temporary Octofan PWM and watchdog safety loop for llama.cpp RPC POC
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/llama.cpp-rpc/bin/octofan-safety-loop
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now octofan-poc-safety.service
}

clone_or_update_llama_cpp() {
  mkdir -p "${INSTALL_ROOT}"
  if [[ -d "${LLAMA_DIR}/.git" ]]; then
    git -C "${LLAMA_DIR}" fetch --all --tags
  else
    git clone https://github.com/ggml-org/llama.cpp.git "${LLAMA_DIR}"
  fi
  git -C "${LLAMA_DIR}" checkout "${LLAMA_CPP_REF}"
}

build_rpc_server() {
  local cuda_compiler="${CUDACXX:-}"
  if [[ -z "${cuda_compiler}" ]]; then
    cuda_compiler="$(command -v nvcc || true)"
  fi
  if [[ -z "${cuda_compiler}" ]]; then
    echo "nvcc not found in PATH after CUDA toolkit install." >&2
    exit 1
  fi

  cmake -S "${LLAMA_DIR}" -B "${BUILD_DIR}" \
    -DGGML_CUDA=ON \
    -DGGML_RPC=ON \
    -DLLAMA_BUILD_TESTS=OFF \
    -DCMAKE_CUDA_COMPILER="${cuda_compiler}" \
    -DCMAKE_BUILD_TYPE=Release

  cmake --build "${BUILD_DIR}" --config Release --target ggml-rpc-server -j"$(nproc)" \
    || cmake --build "${BUILD_DIR}" --config Release --target rpc-server -j"$(nproc)"

  local binary=""
  for candidate in \
    "${BUILD_DIR}/bin/ggml-rpc-server" \
    "${BUILD_DIR}/bin/rpc-server" \
    "${BUILD_DIR}/tools/rpc/ggml-rpc-server" \
    "${BUILD_DIR}/examples/rpc/rpc-server"; do
    if [[ -x "${candidate}" ]]; then
      binary="${candidate}"
      break
    fi
  done

  if [[ -z "${binary}" ]]; then
    echo "Could not find built RPC server binary under ${BUILD_DIR}." >&2
    exit 1
  fi

  ln -sfn "${binary}" "${RPC_SYMLINK}"
}

install_systemd_units() {
  install -d -m 0755 "${INSTALL_ROOT}/bin" /etc/llama-rpc

  cat > "${INSTALL_ROOT}/bin/llama-rpc-start" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:?missing instance id}"
PORT="$((5000 + INSTANCE))"
export CUDA_VISIBLE_DEVICES="${INSTANCE}"
export LD_LIBRARY_PATH="/opt/llama.cpp-rpc/llama.cpp/build-rpc-cuda/bin:/opt/llama.cpp-rpc/llama.cpp/build-rpc-cuda/src:/opt/llama.cpp-rpc/llama.cpp/build-rpc-cuda/ggml/src:${LD_LIBRARY_PATH:-}"

RPC_BIN="/opt/llama.cpp-rpc/current-rpc-server"
HELP="$("${RPC_BIN}" --help 2>&1 || true)"

if grep -q -- "--host" <<<"${HELP}" && grep -q -- "--port" <<<"${HELP}"; then
  bind_args=(--host 0.0.0.0 --port "${PORT}")
elif grep -q -- "-H" <<<"${HELP}"; then
  bind_args=(-H 0.0.0.0 -p "${PORT}")
else
  echo "WARNING: RPC binary help does not show host bind flag; falling back to -p ${PORT}" >&2
  bind_args=(-p "${PORT}")
fi

exec "${RPC_BIN}" "${bind_args[@]}" --device CUDA0
EOF
  chmod 0755 "${INSTALL_ROOT}/bin/llama-rpc-start"

  cat > /etc/systemd/system/llama-rpc@.service <<'EOF'
[Unit]
Description=llama.cpp RPC server for GPU %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/llama.cpp-rpc/llama.cpp
Environment=GGML_RPC_DEBUG=1
ExecStart=/opt/llama.cpp-rpc/bin/llama-rpc-start %i
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now llama-rpc@0 llama-rpc@1 llama-rpc@2 llama-rpc@3
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
force_fans_low
stop_existing_docker_stack
install_octofan_safety_service
install_build_deps
install_cuda_if_needed
clone_or_update_llama_cpp
build_rpc_server
install_systemd_units

cat <<EOF
Nodo 2 listo.

Hostname: ${TARGET_HOSTNAME}
llama.cpp ref: ${LLAMA_CPP_REF}
RPC binary: ${RPC_SYMLINK}
RPC ports: 5000, 5001, 5002, 5003

Verificacion:
  systemctl status octofan-poc-safety.service
  systemctl status llama-rpc@0 llama-rpc@1 llama-rpc@2 llama-rpc@3
  ss -ltnp | grep -E ':5000|:5001|:5002|:5003'
  journalctl -u 'llama-rpc@*' -f
EOF
