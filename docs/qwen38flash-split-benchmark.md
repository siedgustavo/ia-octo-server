# Benchmark de split multi-GPU para Qwen3.8-Flash-Next

Comparacion de `tensor` y `layer` sobre el servidor de produccion. El objetivo es
medir el impacto de la topologia PCIe real usando exactamente el mismo modelo,
build y carga en ambos modos.

> **Nota de vigencia.** Las secciones fechadas 2026-08-28 y 2026-09-05 describen
> la topologia PCIe **anterior** (GPU 2 y 3 a Gen2 x1 tras un switch ASM1184e).
> Los risers se reemplazaron el 2026-09-11 y la comparacion se repitio: ver
> "Re-test tras cambio de risers, 2026-09-11" al final. El veredicto vigente
> sigue siendo `--split-mode layer`, pero por un motivo distinto al original.

## Entorno

- Fecha: 2026-08-28 (America/Argentina/Buenos_Aires)
- Host: `octoserver.core.sied.ar`
- Revision desplegada: `842e6c7`
- llama.cpp: build `b10660`, commit `6c84c7d5d8`
- Modelo: `Qwen3.8-Flash-Next-UD-Q4_K_XL`
- Hardware: 4x RTX 3090 de 24 GiB
- GPU 0 y 1: PCIe Gen3 x16
- GPU 2 y 3: PCIe Gen2 x1, ambas detras del mismo switch ASM1184e
- Contexto del servidor: 262144 tokens
- Batch / ubatch: 512 / 128
- KV cache: Q8_0 para K y V
- Flash Attention: habilitado

## Metodologia controlada

Cada escenario se prueba con el servidor ya cargado y sin otras solicitudes
activas. Se realizan tres repeticiones mediante `POST /completion` con:

- prompt fijo formado por una cabecera por repeticion y 260 repeticiones de
  `The quick brown fox crosses the quiet valley while the server measures deterministic inference performance. `
- 4177 tokens de prompt efectivos
- 256 tokens de salida forzados con `ignore_eos: true`
- `temperature: 0`, `seed: 1234`
- `cache_prompt: false`
- respuesta no streaming

Antes de cada repeticion se consulta `/slots` y se aborta el ensayo si existe
otro slot procesando. Los TPS se toman del objeto `timings` devuelto por
llama.cpp, no del tiempo medido por el cliente.

## Resultados

### Tensor split

Configuracion:

```text
--split-mode tensor
--tensor-split 1,1,1,1
```

| Repeticion | Prompt tokens | Prompt tok/s | Tokens generados | Generacion tok/s | Tiempo cliente |
|---:|---:|---:|---:|---:|---:|
| 1 | 4177 | 52.617 | 256 | 16.484 | 96.557 s |
| 2 | 4177 | 52.650 | 256 | 16.291 | 95.588 s |
| 3 | 4177 | 52.682 | 256 | 16.161 | 95.651 s |
| **Promedio** | **4177** | **52.650** | **256** | **16.312** | **95.932 s** |

Como referencia no controlada, una solicitud real observada inmediatamente
antes del benchmark proceso 14384 tokens nuevos, con 9978 tokens reutilizados
del contexto, a 50.07 tok/s y genero 83 tokens a 13.04 tok/s. Esto muestra el
impacto del contexto largo sobre el TPS de generacion y no debe compararse de
forma directa con el ensayo controlado de 4177 tokens.

Durante el arranque en modo tensor llama.cpp registro:

```text
NCCL init failed; falling back to internal AllReduce
internal AllReduce init failed; falling back to meta-backend butterfly
```

### Layer split

Configuracion:

```text
--split-mode layer
--tensor-split 1,1,1,1
```

| Repeticion | Prompt tokens | Prompt tok/s | Tokens generados | Generacion tok/s | Tiempo cliente |
|---:|---:|---:|---:|---:|---:|
| 1 | 4177 | 535.365 | 256 | 43.056 | 13.746 s |
| 2 | 4177 | 567.177 | 256 | 44.470 | 13.745 s |
| 3 | 4177 | 575.023 | 256 | 42.807 | 13.697 s |
| **Promedio** | **4177** | **559.188** | **256** | **43.444** | **13.729 s** |

El modo layer cargo correctamente los cuatro slots de 262144 tokens. No emitio
los fallbacks de NCCL/AllReduce vistos en tensor. La VRAM en reposo quedo
repartida asi:

| GPU | VRAM usada |
|---:|---:|
| 0 | 23938 MiB |
| 1 | 21640 MiB |
| 2 | 21890 MiB |
| 3 | 21192 MiB |

## Comparacion

| Metrica promedio | Tensor | Layer | Mejora de layer |
|---|---:|---:|---:|
| Prompt processing | 52.650 tok/s | 559.188 tok/s | 10.62x |
| Generacion | 16.312 tok/s | 43.444 tok/s | 2.66x |
| Tiempo total del cliente | 95.932 s | 13.729 s | 6.99x mas rapido |

Para esta topologia PCIe, `layer` es claramente superior en el ensayo
controlado. Reduce la comunicacion continua entre las cuatro GPU y evita que el
enlace Gen2 x1 compartido por GPU 2 y 3 penalice cada operacion paralelizada.

Al finalizar el ensayo se detuvo el contenedor temporal layer y se restauro el
servicio original en modo tensor para cerrar la prueba de forma segura. Luego de
revisar los resultados se eligio dejar `layer` como configuracion permanente
hasta reemplazar los risers PCIe.

## Ajuste para contexto largo

Con cuatro slots automaticos, una sesion de OpenCode completo una solicitud con
68519 tokens, pero la solicitud siguiente provoco un OOM CUDA en GPU 0 al
reservar un buffer temporal de `top_k/argsort`. La GPU 0 tenia solo 190 MiB
libres, mientras las otras conservaban entre 2.2 y 2.9 GiB.

Se fijo `--parallel 1` para conservar el contexto nativo de 262144 tokens en la
unica sesion usada por OpenCode y evitar reservar recursos para tres sesiones
concurrentes sin uso. En esta arquitectura solo libero unos 96 MiB adicionales
en GPU 0, por lo que no fue suficiente por si solo.

Tambien se ajusto el reparto layer a `--tensor-split 0.9,1,1,1.1`. GPU 0 recibe
una fraccion menor de pesos para dejar margen a los buffers temporales, sin
cambiar contexto, batch, ubatch, cache KV, cuantizacion ni cantidad de capas en
GPU. La fraccion adicional de GPU 3 dirige hacia ella la capa desplazada, porque
es la placa con mayor margen disponible. El impacto esperado sobre el TPS de una
sesion es minimo porque solo cambia la ubicacion de las capas.

Estado de VRAM en reposo despues del ajuste:

| GPU | VRAM usada | VRAM libre |
|---:|---:|---:|
| 0 | 22256 MiB | 1872 MiB |
| 1 | 21556 MiB | 2571 MiB |
| 2 | 21806 MiB | 2321 MiB |
| 3 | 22706 MiB | 1421 MiB |

Una repeticion de control con la misma carga de 4177 tokens de prompt y 256 de
salida obtuvo 533.311 tok/s de prompt, 43.512 tok/s de generacion y 13.711 s de
tiempo cliente. Frente al promedio layer original, la generacion se mantuvo
equivalente (43.444 tok/s antes) y el prompt bajo aproximadamente 4.6%.

## Criterio de comparacion

Se compararan por separado los promedios de prompt processing y generacion. La
decision final tambien debe considerar estabilidad, errores de arranque,
distribucion de VRAM y comportamiento con contexto largo; no solo el mayor TPS
de una unica repeticion.

## Prueba de MTP (speculative decoding), 2026-09-05

A diferencia de GLM-5.3-Flash (ver `docs/glm53flash-benchmark.md`), Qwen3.8-
Flash-Next entra completo en VRAM (`--n-gpu-layers 999`, sin offload a CPU).
Es el escenario GPU-bound donde MTP promete ganancia segun la
[guia de Unsloth](https://unsloth.ai/docs/models/qwen3.8-next) (1.3-1.7x,
benchmarkeado en 1x RTX 6000 PRO). Se armo una build de prueba para
confirmarlo en esta topologia (4x RTX 3090, risers x1 en GPU 2/3).

### Motivo de la build separada

El soporte `--spec-type draft-mtp` para la arquitectura qwen4exp **no esta
mergeado en `ggml-org/llama.cpp` upstream** al 2026-09-05 (PRs
[#27836](https://github.com/ggml-org/llama.cpp/pull/27836) y
[#28243](https://github.com/ggml-org/llama.cpp/pull/28243), ambos abiertos).
Se uso la rama de trabajo del maintainer de Unsloth,
`danielhanchen/llama.cpp` rama `qwen4exp/mtp` (commit del mismo dia,
`d1a92352c`), documentada en el
[README de MTP de Unsloth](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/blob/main/MTP/README.md).
Ver `llamacpp/Dockerfile.qwen38flash-mtp-test` y
`docker-compose.qwen38flash-mtp-test.yml` (build de prueba, no de
produccion).

Draft head usado: `mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf` (2.6 GB,
comparte embeddings con el modelo principal), bajado a
`/opt/models-archive/MTP/` en octoserver.

### Problema de VRAM al cargar el draft

Con la config de produccion (ctx 262144, `tensor-split 0.9,1,1,1.1`), GPU 3
solo tenia 1.4 GiB libres y el draft necesita ~2.7 GiB contiguos: fallo con
`cudaMalloc failed: out of memory` en CUDA3. Se ajusto para la prueba a
`ctx-size 131072` y `tensor-split 1,1,1,0.85` (menos peso del modelo
principal en GPU 3) para dejarle margen al draft. Con eso cargo sin
problemas: VRAM en reposo quedo en 22826 / 22122 / 22372 / 19990 MiB (GPU
0-3).

### Metodologia

Mismo benchmark controlado que el resto del documento (prompt fijo de 6392
tokens tokenizados, 256 de salida forzados con `ignore_eos: true`,
`temperature: 0`, `seed: 1234`, `cache_prompt: false`), 3 repeticiones,
`--spec-draft-n-max 2` (default recomendado por Unsloth). Se corrio primero
un baseline en vivo contra el `qwen38flash` de produccion (sin MTP, mismo
prompt) para tener una referencia fresca antes de tocar nada.

| Config | Prompt tok/s | Generacion tok/s |
|---|---:|---:|
| Baseline produccion (sin MTP, ctx 262144) | ~554 | ~41.6 |
| Con MTP (`draft-mtp`, ctx 131072, mismo build de prueba) | ~356 | **~66.5** |

**Mejora de generacion: ~1.6x**, en linea con lo que promete Unsloth (1.3-
1.7x) y muy por encima de lo que paso con GLM (donde MTP *empeoraba* la
generacion). El prompt processing baja (~356 vs ~554 tok/s) porque el ctx de
prueba es menor y hay overhead de cargar/evaluar el draft, pero no es la
metrica que importa para uso interactivo.

Estadisticas de aceptacion del draft (logs del servidor,
`--verbosity` default):

```text
draft acceptance = 0.91667 (165 accepted / 180 generated), mean len = 2.83
```

91.7% de aceptacion, longitud media de draft aceptado 2.83 tokens. Con
`nvidia-smi dmon` durante la generacion se vio actividad real de SM en las 4
GPUs (picos ~40-85%), a diferencia de GLM donde la GPU quedaba al 0% en
generacion. Confirma la hipotesis: en un modelo que entra completo en VRAM
el cuello es computo GPU, y ahi MTP si ayuda.

### Limitaciones de esta prueba, antes de llevarla a produccion

1. **Rama no oficial y en movimiento.** `qwen4exp/mtp` tuvo un commit el
   mismo dia de la prueba (fix de un bug de posicionamiento M-RoPE). No es
   una base estable para dejar corriendo sin supervision.
2. **Se bajo el contexto operativo** de 262144 a 131072 solo para que el
   draft entrara en VRAM con el `tensor-split` actual. Habria que
   re-explorar el reparto (auto-fit si esta disponible en esta rama, u otro
   `tensor-split`) para recuperar el contexto completo sin perder margen
   para el draft.
3. No se probo con contexto largo real de una sesion de OpenCode (~9-15k
   tokens de prompt inicial), solo con el prompt controlado de 6392 tokens.
   Falta confirmar que la aceptacion del draft se mantenga con prompts mas
   realistas y que no haya interaccion rara con el KV cache persistente a
   disco (`docs/kv-cache-persistence.md`) o el `--cache-ram` de prompts.
4. No se probo con `--spec-draft-n-max` distinto de 2, ni el impacto en VRAM
   de checkpoints de contexto (`--ctx-checkpoints`) combinados con el draft.

### Prueba end-to-end con OpenCode real, 2026-09-05

El benchmark anterior mide solo throughput puro (`/completion` controlado).
Para saber si la ganancia se siente en el uso real se corrieron las mismas
tareas con el cliente de OpenCode contra ambos builds, alternando (se
para uno, se levanta el otro; no entran juntos en VRAM). Se agrego
temporalmente un provider `llamacpp-qwen38-mtp-test` en
`~/.config/opencode/opencode.json` apuntando al puerto 8092, despues
revertido.

**Set 1 (3 tareas cortas, sesiones nuevas, cada una paga el prefill completo
del system prompt de OpenCode):**

| Tarea | Baseline (sin MTP) | Con MTP |
|---|---:|---:|
| 1. Leer archivo grande (~230 lineas) y resumir | 51.7 s | 65.3 s |
| 2. `git log` + responder | 12.7 s | 11.7 s |
| 3. Escribir y ejecutar script python | 17.7 s | 15.0 s |
| **Total** | **82.1 s** | **92.0 s** |

MTP perdio en la tarea 1 (archivo mas pesado) y gano por poco en 2 y 3.
Motivo: el prompt processing de la build de prueba es ~36% mas lento (~356
vs ~554 tok/s, ver seccion anterior) por el contexto reducido a 131072 y el
overhead de evaluar el draft. Cuando el prefill domina el tiempo total (leer
un archivo grande, primer turno de una sesion), esa perdida tapa la
ganancia de generacion.

**Set 2 (archivo mas chico, 2 turnos en la misma sesion):**

| Turno | Baseline | Con MTP |
|---|---:|---:|
| 1 (frio, prefill completo) | 45.1 s | 32.1 s |
| 2 (prompt cacheado + 1 tool call) | 14.3 s | 17.1 s* |

\* Turno 2 de MTP incluyo un llamado a herramienta que fallo (`rg` no
instalado en el contenedor) y reintento con `grep`, agregando latencia extra
no comparable 1 a 1.

**Intento de medir el caso mas relevante (turno de solo-generacion, con el
prompt ya cacheado) fallo por un problema metodologico:** alternar los
containers via `docker compose down`/`up` destruye el KV cache en memoria de
`llama-server` (el save/restore a disco de `docs/kv-cache-persistence.md`
solo se dispara con `SIGTERM`/`stop`, no lo intente en este ciclo rapido de
pruebas). El intento de continuar la sesion de MTP tras haber levantado y
bajado el contenedor un par de veces termino re-prefilleando toda la
conversacion desde cero (65.8 s en vez de los ~5-10 s esperados de un hit de
cache). **No se pudo confirmar en esta sesion si la ganancia de generacion
se siente en el escenario de uso mas comun (turnos incrementales con
cache_prompt activo)**, que es justamente el caso que motiva
`docs/kv-cache-persistence.md` y probablemente el que mas se beneficiaria
de MTP en un dia real de trabajo.

En todas las corridas los resultados fueron **correctos** (tool calls
validos, respuestas coherentes, sin crashes ni reinicios del servidor).

### Veredicto

**Mixto, no es un reemplazo claro todavia.** El benchmark controlado (misma
carga, sin variabilidad de contenido) confirma una ganancia real de
generacion (~1.6x) con uso genuino de GPU. Pero en uso real vía OpenCode esa
ganancia se diluye o se revierte porque:

1. El prompt processing es ~36% mas lento en la build de prueba, y OpenCode
   paga un prefill de varios miles de tokens en cada sesion nueva. Con
   archivos grandes de por medio, esto pesa mas que la generacion mas
   rapida.
2. No se pudo validar el caso de uso donde mas debería notarse (turnos
   subsiguientes de una sesion larga con `cache_prompt` activo), por una
   limitacion del metodo de prueba (alternar containers mata el cache en
   RAM), no porque se haya medido y de negativo.
3. La reduccion de contexto a 131072 es aceptable para el usuario ("pocas
   veces paso los 128k"), asi que no es un bloqueante en si mismo.

**Recomendacion:** no reemplazar produccion todavia. Si se quiere una
respuesta definitiva, la proxima prueba deberia dejar el build de MTP
corriendo sin interrupciones (no alternar containers) durante un dia de uso
real de OpenCode, para que el `cache_prompt`/`--cache-ram` puedan actuar
como en produccion y medir turnos incrementales genuinos, no solo turnos
fríos. Mientras tanto sigue como imagen de prueba documentada
(`octofan/llamacpp:qwen38flash-mtp-test`), no en
`docker-compose.qwen38flash.yml`.

## Re-test tras cambio de risers, 2026-09-11

El benchmark original dejo `layer` como definitivo **"hasta reemplazar los
risers PCIe"**. Los risers se reemplazaron, asi que se repitio la comparacion.

### Topologia nueva

El cambio fue mayor que solo el ancho del enlace: **desaparecio el switch
ASM1184e**. Las cuatro GPU ahora cuelgan directo de root ports del CPU:

```text
+-02.0-[02]-- RTX 3090
+-02.2-[03]-- RTX 3090
+-03.0-[04]-- RTX 3090
+-03.2-[05]-- RTX 3090
```

| Aspecto | Antes (2026-08-28) | Ahora (2026-09-11) |
|---|---|---|
| GPU 0 y 1 | Gen3 x16 | Gen3 x8 |
| GPU 2 y 3 | Gen2 x1, compartido tras ASM1184e | Gen3 x8, root port propio |
| Switch intermedio | Si | No |
| Ancho por GPU 2/3 | ~500 MB/s entre las dos | ~7.9 GB/s cada una |

`nvidia-smi` en reposo reporta `2.5GT/s (downgraded)` por ASPM. Bajo carga las
cuatro negocian Gen3 x8 (`pcie.link.gen.current=3`, `width.current=8`),
verificado muestreando durante el benchmark.

Peer-to-peer sigue **no disponible**, y esto es lo determinante:

```text
nvidia-smi topo -p2p r
GPU0  X    CNS  CNS  CNS
CNS = Chipset not supported
```

Los Xeon E5-2680 v4 no soportan P2P entre root ports distintos y las 3090 no
tienen NVLink bridge. Todo trafico GPU-GPU rebota por RAM del host.

### Resultados

Misma metodologia de la seccion "Metodologia controlada". El prompt tokeniza
4167 tokens en vez de 4177 (0.24% de diferencia, por cambios de plantilla entre
builds); no afecta las conclusiones.

Layer split (`--split-mode layer --tensor-split 0.9,1,1,1.1`, config de prod):

| Repeticion | Prompt tokens | Prompt tok/s | Tokens generados | Generacion tok/s | Tiempo cliente |
|---:|---:|---:|---:|---:|---:|
| 1 | 4167 | 881.378 | 256 | 51.495 | 11.389 s |
| 2 | 4167 | 912.309 | 256 | 51.831 | 9.721 s |
| 3 | 4167 | 908.452 | 256 | 49.714 | 9.950 s |
| **Promedio** | **4167** | **900.713** | **256** | **51.013** | **10.353 s** |

Tensor split (`--split-mode tensor --tensor-split 1,1,1,1`, contenedor temporal
en puerto 8092, mismo build e imagen):

| Repeticion | Prompt tokens | Prompt tok/s | Tokens generados | Generacion tok/s | Tiempo cliente |
|---:|---:|---:|---:|---:|---:|
| 1 | 4167 | 388.254 | 256 | 20.439 | 23.227 s |
| 2 | 4167 | 404.370 | 256 | 20.096 | 23.297 s |
| 3 | 4167 | 402.079 | 256 | 19.724 | 23.591 s |
| **Promedio** | **4167** | **398.234** | **256** | **20.086** | **23.372 s** |

### Comparacion

| Metrica promedio | Tensor | Layer | Ventaja de layer |
|---|---:|---:|---:|
| Prompt processing | 398.234 tok/s | 900.713 tok/s | 2.26x |
| Generacion | 20.086 tok/s | 51.013 tok/s | 2.54x |
| Tiempo total del cliente | 23.372 s | 10.353 s | 2.26x mas rapido |

Ganancia gratis de los risers, sin cambiar un solo flag:

| Metrica | Layer 2026-08-28 | Layer 2026-09-11 | Mejora |
|---|---:|---:|---:|
| Prompt processing | 559.188 tok/s | 900.713 tok/s | 1.61x |
| Generacion | 43.444 tok/s | 51.013 tok/s | 1.17x |
| Tiempo cliente | 13.729 s | 10.353 s | 1.33x |

Evolucion de la brecha entre modos:

| Brecha layer/tensor | 2026-08-28 | 2026-09-11 |
|---|---:|---:|
| Prompt processing | 10.62x | 2.26x |
| Generacion | 2.66x | 2.54x |

### Por que tensor sigue perdiendo

Los risers cerraron la brecha de prompt processing (de 10.62x a 2.26x), que era
el sintoma del ancho de banda. Pero la brecha de generacion casi no se movio
(2.66x -> 2.54x), porque su causa no es el ancho de banda sino la **latencia del
AllReduce sin P2P**. Los logs de arranque en tensor lo muestran:

```text
NCCL init failed (unhandled system error); falling back to internal AllReduce
internal AllReduce init failed (n_devices != 2?); falling back to meta-backend butterfly
```

Dos limitaciones apiladas:

1. NCCL no inicializa (sin P2P, chipset no soportado).
2. El AllReduce interno de llama.cpp **solo soporta 2 dispositivos**
   (`n_devices != 2?`). Con 4 GPU cae si o si al backend `butterfly`.

Tambien aparece, solo en modo tensor:

```text
common_fit_params: failed to fit params to free device memory:
llama_params_fit is not implemented for SPLIT_MODE_TENSOR, abort
```

es decir, el auto-fit de VRAM no existe para tensor; hay que repartir a mano.

Evidencia de que el cuello es sincronizacion y no computo:

- CPU del host nunca paso de **2.4%** durante el benchmark tensor, asi que no
  hubo offload ni bottleneck de CPU.
- `load_tensors: offloaded 49/49 layers to GPU` en ambos modos.
- El `CPU_Mapped model buffer size = 28110.09 MiB` que aparece en tensor
  **tambien aparece en layer**: es el mmap del GGUF, no offload de computo.
- Utilizacion de GPU en tensor: 56-66% en las cuatro a la vez (lockstep,
  esperando el AllReduce). En layer: picos de 77-92%.

VRAM en reposo, modo tensor con reparto uniforme: 285-494 MiB libres por GPU,
bastante mas ajustado que los 1.4-2.6 GiB de layer. Con contexto largo el riesgo
de OOM seria mayor que el ya documentado en "Ajuste para contexto largo".

### Veredicto

**Se mantiene `--split-mode layer`.** La condicion "hasta reemplazar los risers"
ya se cumplio y el resultado se sostiene, pero por un motivo distinto al
original: ya no es el ancho de banda del switch Gen2 x1, sino la ausencia de P2P
en el chipset Xeon E5 v4 sumada al limite de 2 dispositivos del AllReduce
interno de llama.cpp.

Tensor split solo seria competitivo en esta maquina si se dieran P2P por
hardware (plataforma con soporte, o NVLink bridge entre pares de 3090) **y**
NCCL funcional. Ninguna de las dos depende de los risers, asi que no conviene
volver a probar tensor por cambios de cableado PCIe.

Tambien se conserva `--tensor-split 0.9,1,1,1.1`: responde al OOM de GPU 0 por
buffers temporales (ver "Ajuste para contexto largo"), que es un tema de VRAM y
es independiente de la topologia PCIe.

Produccion quedo restaurada en modo layer, healthy, con la distribucion de VRAM
esperada (1421-2571 MiB libres por GPU). El KV cache persistido se regrabo en el
apagado limpio del contenedor de prod, en el mismo modo y split, asi que siguio
siendo coherente y no hubo que invalidarlo.
