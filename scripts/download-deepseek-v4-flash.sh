#!/usr/bin/env bash
set -euo pipefail

repo="${DEEPSEEK_V4_REPO:-unsloth/DeepSeek-V4-Flash-0731-GGUF}"
quant="${DEEPSEEK_V4_QUANT:-UD-IQ2_M}"
models_dir="${MODELS_DIR:-/opt/llamacpp/models}"
target_dir="${models_dir}/deepseek-v4-flash-0731"
base_url="https://huggingface.co/${repo}/resolve/main/${quant}"

mkdir -p "${target_dir}"

for shard in 00001 00002 00003; do
  filename="DeepSeek-V4-Flash-0731-${quant}-${shard}-of-00003.gguf"
  curl --fail --location --continue-at - --retry 5 --retry-delay 5 \
    --output "${target_dir}/${filename}" \
    "${base_url}/${filename}"
done

du -sh "${target_dir}"
