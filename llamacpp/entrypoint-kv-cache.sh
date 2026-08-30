#!/bin/sh
# Envuelve llama-server para persistir el KV cache de cada slot a disco entre
# reinicios del contenedor. No hace nada por sesion de opencode: solo evita
# volver a prefillear el contexto largo cuando el contenedor se reinicia.
# Generico: lo usan tanto Dockerfile (GLM-5.3-Flash) como Dockerfile.qwen38flash.
#
# Requiere que --slot-save-path este entre los args pasados a este script y
# que coincida con SLOT_SAVE_PATH. El cache queda atado a la build de
# llama.cpp, el modelo, la cuantizacion del KV y el tensor-split usados al
# guardarlo: si alguno cambia, el restore puede fallar o devolver basura.
#
# SLOT_COUNT debe coincidir con --parallel (default 1). Cada slot N se
# guarda/restaura como "${KV_CACHE_FILE}.slotN.bin" para no pisarse entre si.
set -e

SLOT_SAVE_PATH="${SLOT_SAVE_PATH:-}"
KV_CACHE_FILE="${KV_CACHE_FILE:-opencode}"
SLOT_COUNT="${SLOT_COUNT:-1}"
PORT=8080

slot_file() {
    echo "${KV_CACHE_FILE}.slot${1}.bin"
}

llama-server "$@" &
SERVER_PID=$!

save_cache() {
    if [ -n "$SLOT_SAVE_PATH" ]; then
        echo "entrypoint: guardando KV cache de $SLOT_COUNT slot(s) en disco antes de apagar..." >&2
        i=0
        while [ "$i" -lt "$SLOT_COUNT" ]; do
            f="$(slot_file "$i")"
            curl -fsS -X POST "http://127.0.0.1:${PORT}/slots/${i}?action=save" \
                -H "Content-Type: application/json" \
                -d "{\"filename\": \"${f}\"}" >&2 \
                || echo "entrypoint: fallo el save del slot ${i} (se sigue apagando igual)" >&2
            i=$((i + 1))
        done
    fi
}

term_handler() {
    save_cache
    kill -TERM "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null
    exit 0
}
trap term_handler TERM INT

if [ -n "$SLOT_SAVE_PATH" ]; then
    echo "entrypoint: esperando el health del servidor para restaurar el KV cache..." >&2
    i=0
    while [ "$i" -lt 240 ]; do
        if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            s=0
            while [ "$s" -lt "$SLOT_COUNT" ]; do
                f="$(slot_file "$s")"
                if [ -f "${SLOT_SAVE_PATH}/${f}" ]; then
                    echo "entrypoint: restaurando KV cache del slot ${s} desde ${SLOT_SAVE_PATH}/${f}..." >&2
                    curl -fsS -X POST "http://127.0.0.1:${PORT}/slots/${s}?action=restore" \
                        -H "Content-Type: application/json" \
                        -d "{\"filename\": \"${f}\"}" >&2 \
                        || echo "entrypoint: fallo el restore del slot ${s}" >&2
                fi
                s=$((s + 1))
            done
            break
        fi
        sleep 5
        i=$((i + 1))
    done
fi

wait "$SERVER_PID"
