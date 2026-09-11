#!/usr/bin/env python3
"""Analiza el JSON de expert_profile.json que emite el expert-profiler.

Uso:
    python3 analyze.py /ruta/expert_profile.json

Reporta, por capa y global, el sesgo de activacion de expertos y el "techo
ideal": que fraccion de activaciones se capturaria si se colocaran los top-N
expertos de cada capa en VRAM (colocacion per-experto, que hoy solo ktransformers
puede hacer; llama.cpp/ik_llama.cpp empacan los expertos de una capa en un unico
tensor y no pueden dividirlos).
"""
import json
import sys


def gini(vals):
    s = sorted(vals)
    n = len(s)
    tot = sum(s)
    if tot == 0 or n == 0:
        return 0.0
    cum = 0.0
    wsum = 0.0
    for x in s:
        cum += x
        wsum += cum
    return (n + 1 - 2.0 * (wsum / tot)) / n


def main(path):
    d = json.load(open(path))
    layers = {int(k): v for k, v in d["layers"].items()}
    total = d["total_selected"]
    print(f"total selecciones (token x expert_used): {total}")
    print(f"capas MoE: {min(layers)}..{max(layers)} (n={len(layers)})\n")

    print("layer  n_exp  used   max%  top8%  gini")
    for il in sorted(layers):
        v = layers[il]
        tot = sum(v)
        if tot == 0:
            continue
        s = sorted(v, reverse=True)
        used = sum(1 for c in v if c > 0)
        print(f"{il:5d}  {len(v):5d}  {used:4d}  {100*s[0]/tot:4.1f}  "
              f"{100*sum(s[:8])/tot:5.1f}  {gini(v):.3f}")

    print("\n=== TECHO IDEAL: %activaciones capturadas con top-N expertos/capa en VRAM ===")
    print("N/capa  %VRAM_exp  %act_global  eficiencia(x)")
    for N in [1, 2, 4, 8, 16, 32, 64, 128]:
        cap = tot = 0
        for v in layers.values():
            s = sorted(v, reverse=True)
            cap += sum(s[:N])
            tot += sum(v)
        pct_act = 100.0 * cap / tot
        pct_vram = 100.0 * N / max(len(v) for v in layers.values())
        print(f"{N:5d}   {pct_vram:6.1f}%   {pct_act:7.1f}%    {pct_act/pct_vram:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "expert_profile.json")
