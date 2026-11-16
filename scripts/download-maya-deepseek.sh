#!/bin/bash
# Baja un Mix del DeepSeek-V4.1-Flash abliterado de orcarouter para Maya (docs/maya-deepseek.md), sin el shard
# de la tabla Engram IQ4_NL (Maya usa Engram-Q6_K). aria2 con 16 conexiones, un archivo a la vez, y sha256 de
# cada uno contra tools/ds4/download_gguf.json de Maya. Retoma lo que quedo a medias.
#
#   QUANT=Mix-128G scripts/download-maya-deepseek.sh      (Mix-256G para el grande)
#
# Requisitos: aria2 (EPEL), Maya clonada en MAYA_DIR, token de HF con los terminos del repo aceptados.
# Correr de a una descarga y con el log del kernel a la vista: ver docs/incidente-2026-11-16-nvme-pico-atx.md.
set -uo pipefail
QUANT=${QUANT:-Mix-128G}
D=${MODELS_DIR:-/opt/models-archive/DeepSeek-V4.1-Flash-1017-abliterated-GGUF}
MAYA_DIR=${MAYA_DIR:-/opt/project-maya}
TOKEN_FILE=${HF_TOKEN_FILE:-/root/.cache/huggingface/token}
MANIFEST=$MAYA_DIR/tools/ds4/download_gguf.json

read -r REPO REV TABLE < <(python3 - "$MANIFEST" "$QUANT" <<'PY'
import json, sys
a = json.load(open(sys.argv[1]))["abliterated"]
print(a["repo"], a["revision"], a["quants"][sys.argv[2]]["table"])
PY
)
mapfile -t FILES < <(python3 - "$MANIFEST" "$QUANT" <<'PY'
import json, sys
q = json.load(open(sys.argv[1]))["abliterated"]["quants"][sys.argv[2]]
print("\n".join(k for k in q["files"] if k != q["table"]))
PY
)
TOKEN=$(cat "$TOKEN_FILE")
mkdir -p "$D/$QUANT"
for k in "${FILES[@]}"; do
  out=$D/$k
  [ -f "$out.ok" ] && { echo "skip $k"; continue; }
  if [ ! -f "$out" ]; then
    for i in $(seq 1 20); do
      aria2c -c -x 16 -s 16 -k 64M --file-allocation=none --auto-file-renaming=false --max-tries=10 \
        --retry-wait=10 --console-log-level=warn --summary-interval=0 --download-result=hide \
        --header="Authorization: Bearer $TOKEN" -d "$(dirname "$out")" -o "$(basename "$out").part" \
        "https://huggingface.co/$REPO/resolve/$REV/$k" && break
      echo "retry $i $k $(date)"; sleep 30
    done
    mv "$out.part" "$out" || exit 1
  fi
  python3 - "$MANIFEST" "$QUANT" "$D" "$k" <<'PY' || exit 1
import hashlib, json, pathlib, sys
manifest, quant, d, k = sys.argv[1:5]
size, sha = json.load(open(manifest))["abliterated"]["quants"][quant]["files"][k]
p = pathlib.Path(d) / k
h = hashlib.sha256()
with open(p, "rb") as f:
    for b in iter(lambda: f.read(1 << 24), b""):
        h.update(b)
ok = p.stat().st_size == size and h.hexdigest() == sha
print(("OK  " if ok else "BAD ") + k, flush=True)
sys.exit(0 if ok else 1)
PY
  touch "$out.ok"
done
echo "ALL_DONE $QUANT (sin $TABLE) $(date)"
