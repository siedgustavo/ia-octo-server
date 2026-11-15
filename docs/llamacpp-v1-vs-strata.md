# llama.cpp v1.0.0 vs Strata (Qwen3.8 Flash Next Huihui V2), 2026-11-14

Pregunta: ¿llama.cpp v1.0.0 (tag del 2026-11-13) ya trae lo que hace rápido a
Strata y permite prescindir de él? Respuesta corta: **todavía no**. Con contexto
corto llama.cpp queda cerca de Strata, pero con contexto largo (el uso real
desde OpenCode) Strata genera 1,4–2,1× más rápido y hace el prefill hasta 1,6×
más rápido.

## Qué trae llama.cpp v1.0.0

- MTP nativo para `qwen4exp` (`--spec-type draft-mtp` + `--model-draft`), sin
  la rama no oficial de Unsloth. Usa el draft de ggml-org
  `/opt/models-archive/MTP/mtp-Qwen3.8-Flash-Next-ggml-org-Q4_0.gguf`.
- MoE cache en VRAM para expertos en RAM (`--moe-cache-mib`,
  `--moe-cache-cpu-share`). Acá no aplica: el Q4_K_XL entra entero en las cuatro
  3090, así que no se usó.
- KV FP8 (`f8_e4m3`). No probado: se mantuvo `q8_0`.

## Método

- Mismo GGUF que Strata (Huihui V2 UD-Q4_K_XL), contexto 262144, un slot,
  `--split-mode layer --fit on --fit-target 1024`, ubatch 256, KV `q8_0`,
  flash-attn. Build CUDA 12.8, sm_86
  (`llamacpp/Dockerfile.llamacpp-v1-test`, `docker-compose.llamacpp-v1-test.yml`).
- Strata en su configuración de producción (`strata/strata-qwen.json`, `--spec 4`).
- `scripts/bench-openai-timings.py`: temperatura 0, sin razonamiento, nonce al
  inicio de cada prompt para que no haya reuso de caché (`cache_n = 0` en todas
  las corridas). Los prompts largos son los `docs/*.md` concatenados. Métricas
  tomadas de `timings`, que ambos motores devuelven en formato llama.cpp.
- 4 GPU limitadas a 250 W en todas las corridas.

## Resultados

Generación (tok/s, decode):

| Caso | Strata | llama.cpp MTP n=3 | llama.cpp MTP n=4 | llama.cpp sin MTP |
| --- | ---: | ---: | ---: | ---: |
| Corto (~60 tok, 256 de salida) | 106 / 144 / 146 | 108–110 | 109–115 | 62–63 |
| Código (~95 tok, 1024 de salida) | 133–139 | 108 | 110–111 | 61 |
| 8.7k de prompt | 95 | 77 | 85 | — |
| 35k de prompt | 97 | 66 | 67 | 49 |
| 111k de prompt | 86 | 41 | 41 | 35 |

Prefill (tok/s):

| Prompt | Strata | llama.cpp MTP n=4 | llama.cpp sin MTP |
| --- | ---: | ---: | ---: |
| 8.7k | 864 | 1035 | — |
| 35k | 1269 | 971 | 1070 |
| 111k | 1509 | 940 | 1067 |

Tiempo total de la request de 111k tokens + 512 de salida: Strata 80 s,
llama.cpp con MTP 131 s, sin MTP 120 s.

Aceptación del draft (aceptados / propuestos): prácticamente igual en ambos
motores. Corto: Strata ~86 %, llama.cpp 87–90 %. Largo: Strata ~55 %,
llama.cpp 57–59 %.

## Lectura

- MTP upstream funciona y vale lo mismo que en Strata en aceptación; con
  contexto corto duplica a llama.cpp (62 → 110 tok/s).
- La diferencia está en el costo de la atención con contexto largo: llama.cpp
  sin MTP cae de 62 a 35 tok/s entre 0 y 111k, y verificar las propuestas del
  draft sobre ese contexto casi anula la ganancia de MTP (35 → 41). Strata
  conserva 86 tok/s. Su prefill también escala con el contexto, mientras que el
  de llama.cpp se mantiene plano en ~1000 tok/s.
- Para el uso diario con OpenCode (system prompt + herramientas + archivos,
  sesiones de 30k–200k tokens) Strata sigue siendo claramente mejor. llama.cpp
  solo gana en prefill corto (<10k) y en funciones: visión, varios slots y
  persistencia del KV.

Decisión: Strata sigue como servicio diario. Reevaluar cuando llama.cpp mejore
la atención con contexto largo para `qwen4exp` (sparse/indexer) o el costo de
verificación de MTP.

## Operación de la prueba

Para parar Strata sin que el watchdog de IA lo vuelva a arrancar
(`docker restart` sobre un container parado lo inicia), se hizo `PUT
/api/config` con `watchdog.ai_recovery_enabled: false` y
`gpu_recovery_restart_containers: []`. Antes se respaldó
`config/octofan.yaml` y al final se restauró ese archivo y la config original
por API.

Efecto observado: mientras `ai_recovery` está desactivado, `_ai_recovery_decision`
sigue sumando fallas. Al reactivarlo ~5 s después de `docker compose start`,
hubo un `docker restart strata-qwen` inmediato durante la carga. Strata cargó
bien igual. Causas, corregidas el 2026-11-15: el controller leía
`State.Health.status` en vez de `Status`, así que nunca veía `starting`, y además
acumulaba fallas con el recovery apagado.
