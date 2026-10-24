#!/usr/bin/env bash
# Descarga FLUX.1-schnell (GGUF Q8_0) y sus encoders para el servicio flux
# de docker-compose.flux.yml (stable-diffusion.cpp sd-server en CPU).
set -euo pipefail

models_dir="${FLUX_MODELS_DIR:-/opt/imagegen/flux}"
hf="https://huggingface.co"

mkdir -p "${models_dir}"

# El ae.safetensors oficial de black-forest-labs esta gated; este mirror tiene
# el mismo sha256 (afc8e282...).
files=(
  "flux1-schnell-q8_0.gguf ${hf}/leejet/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-q8_0.gguf"
  "ae.safetensors ${hf}/second-state/FLUX.1-schnell-GGUF/resolve/main/ae.safetensors"
  "clip_l.safetensors ${hf}/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"
  "t5xxl_fp16.safetensors ${hf}/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"
)

for entry in "${files[@]}"; do
  read -r name url <<<"${entry}"
  echo "Downloading ${name}"
  curl --fail --location --continue-at - --retry 5 --retry-delay 5 \
    --output "${models_dir}/${name}" "${url}"
done

echo "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38  ${models_dir}/ae.safetensors" \
  | sha256sum --check
du -sh "${models_dir}"
