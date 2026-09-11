# Expert activation profiler (GLM-5-Next / llama.cpp)

Herramienta para medir el **sesgo de activacion de expertos** de un modelo MoE
GGUF (probado con GLM-5.3-Flash / arch `glm5next`) corriendo sobre llama.cpp.

Responde una pregunta concreta: cuando el modelo enruta cada token a sus expertos,
¿unos pocos expertos se activan mucho mas que el resto (sesgo aprovechable para
colocar los "calientes" en VRAM) o el uso es casi uniforme?

## Por que existe

El objetivo original era la "plantilla de expertos" de ktransformers (afinidad de
los expertos mas activos a VRAM, los frios a RAM). Ese placement **per-experto**
solo lo hace ktransformers, que en el Octoserver esta bloqueado (exige FP8 +
AVX-512 + ~350 GB RAM; ver `docs/glm53flash-ktransformers-poc.md`).

llama.cpp / ik_llama.cpp SI corren en este hardware, pero empacan los 288 expertos
de cada capa en un **unico tensor 3D** (`blk.N.ffn_up_exps.weight`, dims
`(4096, 2048, 288)`), asi que `--override-tensor` solo puede mover la capa entera,
no expertos individuales. Este profiler cuantifica **cuanto se perderia** por no
poder colocar per-experto.

## Como funciona

Reemplaza el ejemplo `eval-callback` de llama.cpp por una version que instala un
`cb_eval` en el scheduler de ggml. Durante el prefill intercepta el tensor
`ffn_moe_topk-<capa>` (IDs de expertos seleccionados por token, I32) y acumula un
histograma por `(capa, experto)`. Al terminar vuelca:

- Un resumen por capa a stdout (max%, top8%, gini).
- `/tmp/expert_profile.json` con los conteos crudos por capa.

`ffn_moe_topk` es un view NO contiguo (top-k sobre el argsort de 288), por eso el
callback lee `ggml_nbytes` crudos e indexa con los strides reales (`nb`).

## Build (CPU-only, no toca GPUs)

Se compila contra el mismo commit de llama.cpp que usa el servicio de produccion
(`unslothai/llama.cpp @ glm5next/upstream`, commit
`2e0e57f1008053bae4902a772da85e3eb99d4aff`).

```bash
docker run -d --name kt-prof -v /opt/models-archive:/models:ro ubuntu:24.04 sleep infinity
docker exec kt-prof bash -lc '
  apt-get update && apt-get install -y --no-install-recommends \
    git cmake ninja-build build-essential libcurl4-openssl-dev ca-certificates pkg-config
  cd /root && git clone --recurse-submodules https://github.com/unslothai/llama.cpp llama.cpp
  cd llama.cpp && git fetch origin glm5next/upstream \
    && git checkout 2e0e57f1008053bae4902a772da85e3eb99d4aff \
    && git submodule update --init --recursive
'
# Reemplazar el ejemplo por el profiler y compilar solo ese target:
docker cp expert-profiler.cpp kt-prof:/root/llama.cpp/examples/eval-callback/eval-callback.cpp
docker exec kt-prof bash -lc '
  cd /root/llama.cpp
  cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DGGML_CUDA=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_EXAMPLES=ON \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=OFF
  cmake --build build --target llama-eval-callback -j $(nproc)
'
```

## Run

```bash
docker cp prompt.txt kt-prof:/tmp/prompt.txt
docker exec kt-prof bash -lc '
  cd /root/llama.cpp
  ./build/bin/llama-eval-callback \
    -m /models/GLM-5.3-Flash-UD-IQ1_S/GLM-5.3-Flash-UD-IQ1_S-00001-of-00003.gguf \
    -ngl 0 -c 8192 -b 2048 -f /tmp/prompt.txt
'
docker cp kt-prof:/tmp/expert_profile.json .
python3 analyze.py expert_profile.json
```

`-ngl 0` mantiene TODO en CPU/RAM: el profiler no usa las GPUs, asi que puede
correr con el servicio de inferencia levantado sin competir por VRAM. El modelo
se mapea con mmap (RAM ~= tamano del GGUF).

## Resultado de referencia (GLM-5.3-Flash IQ1_S, prompt de ~571 tokens)

Ver `docs/glm53flash-expert-affinity.md`. Resumen: sesgo bajo en capas iniciales
(gini ~0.25) que crece con la profundidad (gini ~0.67); con los top-8 expertos de
cada capa (2.8% del peso de expertos) se capturaria ~21% de las activaciones
globales (~26% en capas profundas). Hay senal real, pero vive en la granularidad
per-experto que llama.cpp no puede direccionar.
