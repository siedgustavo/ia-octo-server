# Afinidad de expertos de GLM-5.3-Flash: datos reales

Medicion empirica de cuan sesgada es la activacion de expertos de GLM-5.3-Flash,
para evaluar si la "plantilla de expertos" (calientes a VRAM, frios a RAM) tiene
beneficio real en el Octoserver.

Complementa a `glm53flash-ktransformers-poc.md` (por que ktransformers no corre
aca) con el dato que faltaba: **aunque pudieramos colocar por-experto, cuanto
ganariamos?**

## Metodo

- Herramienta: `tools/expert-profiler/` (patch del ejemplo `eval-callback` de
  llama.cpp que cuenta activaciones del tensor `ffn_moe_topk` por capa/experto).
- Modelo: `GLM-5.3-Flash-UD-IQ1_S` (GGUF, arch `glm5next`, 288 expertos routed por
  capa MoE, capas 3..44; las capas 0-2 son densas).
- Ejecucion: CPU-only (`-ngl 0`), prompt representativo de ~571 tokens (mezcla
  espanol/ingles/codigo, estilo agente). No usa GPUs; qwen38flash siguio healthy.
- Muestra: 191.856 selecciones (token x expert_used). Suficiente para el patron
  grueso; para conclusiones finas conviene un corpus mas grande.

## Resultado 1: el uso NO es uniforme, y el sesgo crece con la profundidad

Indice de Gini de la distribucion de activaciones por capa (0 = uniforme, 1 =
todo en un experto):

| Rango de capas | Gini tipico | Interpretacion |
|---|---|---|
| 3-6 (iniciales) | ~0.25-0.29 | casi uniformes, sin experto dominante |
| 7-17 (medias) | ~0.43-0.56 | sesgo moderado |
| 18-44 (profundas) | ~0.55-0.67 | sesgo claro |

Casi todos los expertos se activan (used ~255-288 de 288 por capa): **no hay
expertos muertos** que se puedan descartar gratis.

## Resultado 2: el "techo ideal" de una plantilla per-experto

Si pudieramos colocar en VRAM los **top-N expertos de cada capa** (lo que hace
ktransformers y llama.cpp no), la fraccion de activaciones atendida desde GPU
seria:

| N/capa | % del peso de expertos en VRAM | % activaciones capturadas | Eficiencia (%act / %VRAM) |
|---:|---:|---:|---:|
| 1 | 0.3% | 4.9% | 14.1x |
| 2 | 0.7% | 8.4% | 12.1x |
| 4 | 1.4% | 13.8% | 10.0x |
| 8 | 2.8% | 21.3% | 7.7x |
| 16 | 5.6% | 31.1% | 5.6x |
| 32 | 11.1% | 43.8% | 3.9x |
| 64 | 22.2% | 60.8% | 2.7x |
| 128 | 44.4% | 81.8% | 1.8x |

En capas profundas (30-44) el top-8 captura ~25.8%; en las iniciales (3-6) solo
~7.5%.

Lectura: **hay senal real y explotable** (7.7x de eficiencia con top-8 vs
colocacion al azar), pero con rendimientos rapidamente decrecientes. El sesgo se
concentra en un puñado de expertos por capa, no en capas enteras.

## Conclusion: la senal esta en la granularidad que el motor viable no direcciona

- El sesgo aprovechable vive **dentro** de cada capa (unos expertos mas calientes
  que otros), no **entre** capas (todas procesan todos los tokens ~por igual).
- llama.cpp / ik_llama.cpp empacan los 288 expertos de una capa en un tensor
  atomico -> `-ot` solo coloca por capa -> **no pueden capturar este sesgo**.
- ktransformers SI coloca per-experto (es exactamente su feature `frequency`),
  pero esta bloqueado para GLM-5-Next en este hardware (FP8 + AVX-512 + 350 GB;
  ver `glm53flash-ktransformers-poc.md`).

Por lo tanto, en el Octoserver actual la plantilla de expertos por frecuencia
**no es realizable con software que corra en el hardware**, aunque los datos
confirman que el beneficio teorico existe (moderado). La idea era correcta; el
limite es de herramientas, no de concepto.

## Que cambiaria el panorama

- Colocacion **per-experto** en un motor GGUF (feature inexistente hoy; requeriria
  desempacar los expertos o un dispatch tipo ktransformers en llama.cpp).
- O ktransformers habilitado (CPU con AVX-512/AMX + RAM suficiente) para usar su
  estrategia `frequency` nativa.
- El profiler (`tools/expert-profiler/`) queda para re-medir con otros modelos
  MoE (Qwen3-Next, etc.) o corpus mas grandes, y para alimentar decisiones de
  `--n-cpu-moe` / `-ot` por-capa si en el futuro cambia la topologia (risers).
  **La topologia ya cambio el 2026-09-11**: las cuatro GPU pasaron de
  (Gen3 x16, Gen3 x16, Gen2 x1, Gen2 x1 tras switch) a Gen3 x8 directo a root
  ports. Es el escenario que motivaba este punto, asi que re-barrer
  `--n-cpu-moe` / `-ot` esta pendiente. Ver
  `docs/glm53flash-benchmark.md`, "Cambio de topologia PCIe, 2026-09-11".
  Ojo: esto **no** habilita la colocacion per-experto, que sigue bloqueada por
  las limitaciones de herramientas descritas arriba.

## Estado

- `tools/expert-profiler/`: fuente del profiler, prompt, analizador y JSON de
  muestra (`expert_profile.sample.json`).
- Contenedores POC (`kt-poc`, `kt-prof`) eliminados; `/opt/models-archive` intacto.
- `qwen38flash` nunca se detuvo para esta medicion (profiler CPU-only) y quedo
  healthy.
