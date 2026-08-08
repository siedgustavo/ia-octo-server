#!/usr/bin/env bash
set -euo pipefail

models_dir="${COMFYUI_MODELS_DIR:-/opt/imagegen/comfyui/models}"
checkpoint_dir="${models_dir}/checkpoints"
checkpoint="${checkpoint_dir}/flux1-dev-fp8.safetensors"
url="https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors"

mkdir -p "${checkpoint_dir}"

if [[ -f "${checkpoint}" ]] && [[ "$(stat -c %s "${checkpoint}")" == "17246524772" ]]; then
  echo "FLUX.1-dev FP8 is already installed at ${checkpoint}"
  exit 0
fi

echo "Downloading FLUX.1-dev FP8 to ${checkpoint}"
curl --fail --location --continue-at - --retry 5 --retry-delay 5 \
  --output "${checkpoint}" "${url}"

actual_size="$(stat -c %s "${checkpoint}")"
if [[ "${actual_size}" != "17246524772" ]]; then
  echo "Unexpected checkpoint size: ${actual_size} bytes" >&2
  exit 1
fi

echo "Installed ${checkpoint} (${actual_size} bytes)"
