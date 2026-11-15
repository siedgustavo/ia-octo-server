#!/usr/bin/env python3
"""Benchmark neutral para servidores OpenAI-compatibles (Strata / llama-server).

Usa los `timings` que ambos motores devuelven (formato llama.cpp) mas el tiempo
de pared del cliente. Cada request lleva un nonce al principio para que ningun
motor reutilice prefijo cacheado.

uso: bench.py URL MODEL LABEL OUT.jsonl DOCS_DIR
"""
import json
import pathlib
import sys
import time
import urllib.request
import uuid

url, model, label, out_path, docs_dir = sys.argv[1:6]

docs = "\n\n".join(p.read_text() for p in sorted(pathlib.Path(docs_dir).glob("*.md")))


def doc_chars(n: int) -> str:
    text = docs
    while len(text) < n:
        text += "\n\n" + docs
    return text[:n]


SHORT = "Escribe una funcion de busqueda binaria en Python con docstring y un ejemplo de uso."
CODE = (
    "Implementa en Python una cache LRU thread-safe con TTL por entrada, sin usar functools. "
    "Incluye type hints, docstrings y una bateria de tests con pytest que cubra expiracion, "
    "desalojo y concurrencia. Devuelve solo el codigo."
)

CASES = [
    # (nombre, prompt, max_tokens, repeticiones)
    ("short", SHORT, 256, 3),
    ("code", CODE, 1024, 2),
    ("long8k", doc_chars(28000) + "\n\nResume el documento anterior en 10 puntos.", 512, 1),
    ("long32k", doc_chars(110000) + "\n\nResume el documento anterior en 10 puntos.", 512, 1),
    ("long100k", doc_chars(340000) + "\n\nEnumera los incidentes de hardware mencionados en el documento anterior.", 512, 1),
]

only = set(sys.argv[6].split(",")) if len(sys.argv) > 6 else None


def call(prompt: str, max_tokens: int) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": f"[{uuid.uuid4().hex}]\n" + prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=3600) as resp:
        data = json.load(resp)
    wall = time.monotonic() - t0
    t = data.get("timings", {})
    return {
        "wall_s": round(wall, 2),
        "prompt_n": t.get("prompt_n"),
        "cache_n": t.get("cache_n"),
        "prompt_tps": round(t.get("prompt_per_second", 0), 1),
        "gen_n": t.get("predicted_n"),
        "gen_tps": round(t.get("predicted_per_second", 0), 1),
        "draft_n": t.get("draft_n"),
        "draft_acc": t.get("draft_n_accepted"),
        "finish": data["choices"][0].get("finish_reason"),
        "head": (data["choices"][0]["message"].get("content") or "")[:80].replace("\n", " "),
    }


call("Responde OK", 8)  # warmup
with open(out_path, "a") as out:
    for name, prompt, max_tokens, reps in CASES:
        if only and name not in only:
            continue
        for i in range(reps):
            r = {"label": label, "case": name, "rep": i + 1, **call(prompt, max_tokens)}
            print(json.dumps(r, ensure_ascii=False), flush=True)
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
