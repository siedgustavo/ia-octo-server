# GLM-5.3-Flash en el Octoserver: tuning y lecciones

Registro completo de la puesta a punto de GLM-5.3-Flash sobre las cuatro
RTX 3090 del Octoserver, usando llama.cpp con el soporte GLM-5-Next de Unsloth.
La instancia reemplaza temporalmente al servicio Qwen3.8-Flash-Next y queda
expuesta como API compatible con OpenAI en el puerto 8090.

Este documento consolida varias iteraciones de prueba. La configuracion vigente
esta al final, en "Configuracion final desplegada".

> **Nota de vigencia (2026-09-11).** Las mediciones fechadas 2026-08-29 se
> tomaron con la topologia PCIe **anterior** (GPU 2 y 3 a Gen2 x1 tras un switch
> ASM1184e). Los risers se reemplazaron: hoy las cuatro GPU corren a Gen3 x8
> directo a root ports del CPU. GLM se **re-benchmarkeo**: la generacion subio
> ~33% (15.4 -> 20.5 tok/s), se adopto `--fit-target 512` (21.5 tok/s) y el
> "hallazgo contraintuitivo" de la conclusion 3 quedo **refutado**. Ver
> "Cambio de topologia PCIe, 2026-09-11" al final; ante contradicciones, mandan
> las secciones del 2026-09-11.

## Entorno

- Fecha: 2026-08-29 (America/Argentina/Buenos_Aires)
- Host: `octoserver.core.sied.ar`
- Imagen CUDA: CUDA 12.6.3, compilada especificamente para Ampere `sm_86`
- Builds de llama.cpp usados:
  - `glm5next-pr27754` (build 10667, commit `2e0e57f10`): primera prueba con Q2.
  - `glm5next-mtp-27752-test` (build 10692, commit `1f817ef96`): build final,
    incorpora kernels Gated DeltaNet/DSA de GLM5Next y el grafo MTP.
- Hardware: 4x RTX 3090 de 24 GiB
- CPU: 2x Xeon E5-2680 v4 (28 cores / 56 threads), sin AVX-512
- GPU 0 y 1: PCIe Gen3 x16
- GPU 2 y 3: PCIe Gen2 x1, detras de risers (registran errores corregibles)
- Modelos GGUF disponibles en `/opt/models-archive`:
  - `GLM-5.3-Flash-UD-Q2_K_XL` (4 shards, ~109 GB)
  - `GLM-5.3-Flash-UD-IQ1_S` (3 shards, ~93 GB)

Referencias:

- [Guia GLM-5.3-Flash de Unsloth](https://unsloth.ai/docs/models/glm-5.3-flash)
- [PR 27754 de llama.cpp](https://github.com/ggml-org/llama.cpp/pull/27754)

## El problema central

GLM-5.3-Flash es un MoE de 321B parametros totales con 18B activos por token.
La suma de VRAM de las cuatro placas es 96 GiB, pero eso **no** equivale a una
GPU de 96 GiB: hay que reservar KV cache, buffers de computo, estructuras CUDA,
y algunas asignaciones deben entrar completas y contiguas en una sola GPU.

Ni Q2_K_XL (~109 GB) ni IQ1_S (~93 GB) entran completos con contexto largo, asi
que una parte de los expertos MoE queda en CPU/RAM (`--n-cpu-moe`). Ese tramo en
CPU, sumado a la latencia de mover activaciones entre GPUs por los risers x1 de
GPU 2/3, es el cuello de botella real de la generacion.

Sintoma caracteristico: durante la **generacion** las GPU quedan practicamente
al 0% de utilizacion (picos de SM ~13% solo en prompt). No falta potencia de
calculo ni temperatura: el limite es alimentar los expertos y coordinar capas.

## Comparativa con Qwen3.8-Flash-Next

Qwen rinde mucho mejor (~43 tok/s de generacion) por una razon simple: **entra
completo en VRAM**. GLM no. `split-mode layer` reparte trabajo igual en ambos,
pero no aumenta la VRAM total ni evita el tramo en CPU.

| Caracteristica | Qwen3.8-Flash-Next | GLM-5.3-Flash |
|---|---:|---:|
| Parametros totales / activos | 125B / 6B | 321B / 18B |
| Modelo completo en VRAM | Si | No |
| MoE en CPU | 0 capas | ~34 capas |
| Generacion medida (2026-08) | ~43 tok/s | ~15 tok/s |
| Generacion medida (2026-09-11) | ~51 tok/s | ~21.5 tok/s |

## Iteraciones de prueba

Todas las mediciones de generacion usan la misma carga controlada
(`cache_prompt=false`), sobre el mismo hardware y en modo `layer`.

### 1. Cuantizacion: Q2_K_XL vs IQ1_S

Con `n-cpu-moe 34` (mismo offload para comparar limpio):

| Cuantizacion | Prompt tok/s | Generacion tok/s | Tiempo total |
|---|---:|---:|---:|
| Q2_K_XL (~109 GB) | 41.0 | 6.54 | 141.2 s |
| IQ1_S (~93 GB) | 46.8 | 7.13 | 125.0 s |

IQ1_S es ~14% mas rapida en prompt, ~9% en generacion y ademas ocupa ~12 GiB
menos de RAM. Se adopta IQ1_S como base.

### 2. Contexto: 262k vs 128k

El usuario fijo el contexto operativo. Bajar de 262144 a 131072 (128k) libera
KV cache; con auto-fit ese margen se traduce en mas expertos en GPU:

| Contexto | Prompt tok/s | Generacion tok/s |
|---|---:|---:|
| 262144 (auto-fit) | ~29 | ~13.1 |
| 131072 (auto-fit) | ~22 | **~15.4** |

128k mejora la generacion (+11-17%), que es la metrica que domina la experiencia
interactiva. Se adopta 128k.

### 3. Reparto: auto-fit vs placement manual

`--fit on` (auto-fit) calcula el placement de capas y expertos segun la VRAM
real de cada GPU. Se comparo contra bajar `--n-cpu-moe` a mano (mas expertos en
GPU) con distintos `--tensor-split`:

| Config (128k, IQ1) | Prompt tok/s | Generacion tok/s |
|---|---:|---:|
| auto-fit (`--fit on`) | ~22 | **~15.4** |
| `n-cpu-moe 30`, split `1.4,1.4,0.6,0.6` | 34.4 | 8.7 |
| `n-cpu-moe 28`, split `1,1,1,1` | 36.3 | ~10 |

**Hallazgo contraintuitivo:** mover mas expertos a la GPU **acelera el prompt
processing pero frena la generacion**. Motivo: en modo `layer` cada token
atraviesa las 4 GPU en secuencia; concentrar mas capas/expertos aumenta el
trafico de activaciones a traves de los risers x1 de GPU 2/3, que es lento.
El auto-fit balancea mejor y gana en generacion. **Para generacion, el balance
entre GPUs importa mas que cuantos expertos hay en GPU.**

### 4. MTP (Multi-Token Prediction / speculative decoding)

El build final incluye el grafo MTP de GLM (`blk.45`), activable con
`--spec-type draft-mtp`. En la DGX Spark, MTP lleva GLM Q2 de ~17 a ~25 tok/s.

Resultado en el Octoserver:

| Config (262k, IQ1) | Prompt tok/s | Generacion tok/s | Aceptacion draft |
|---|---:|---:|---:|
| sin MTP (auto-fit) | 29.1 | 13.1 | - |
| con MTP (`draft-mtp`) | 34.6 | **9.0** | 96.9% |

**MTP se descarta.** La prediccion es excelente (acepta 96,9% de los tokens
draft, mean len 3.89), pero **baja** la generacion. La razon vuelve a ser el
cuello: la GPU esta al 0% en generacion, el limite es el MoE en CPU. Verificar
varios tokens en paralelo contra expertos-en-CPU cuesta mas de lo que ahorra.
MTP solo acelera cuando la GPU es el cuello, y aca no lo es.

Ademas, activar MTP agrega un compute buffer de ~3,2 GiB en GPU 0 que causa OOM
si no hay margen; requiere subir `--fit-target` o bajar `--ubatch-size`.

## Configuracion final desplegada

Definida en `docker-compose.glm53flash.yml`:

```text
image: octofan/llamacpp:glm5next-mtp-27752-test
--model  GLM-5.3-Flash-UD-IQ1_S (3 shards)
--alias  glm-5.3-flash-iq1-s
--split-mode layer
--fit on
--fit-target 1024,1024,1024,1024
--ctx-size 131072
--parallel 1
--batch-size 512
--ubatch-size 128
--flash-attn on
--temp 1.0
--top-p 0.95
--chat-template-kwargs {"reasoning_effort":"max"}
--jinja --metrics
env: NVIDIA_TF32_OVERRIDE=0
```

Notas:

- `--flash-attn on`: en este build no rompe MLA (a diferencia del build previo
  con Q2, donde habia que dejarlo off) y libera ~8-9 GiB/GPU, margen que el
  auto-fit aprovecha para colocar mas expertos.
- Con esta config queda ~1,0-1,7 GiB libres por GPU tras crear el contexto.

Rendimiento resultante:

| Metrica | Valor |
|---|---:|
| Prompt processing | ~22 tok/s |
| Generacion | **~15.4 tok/s** |

> **Desactualizado (2026-09-11).** `--fit-target` paso a `512,512,512,512` tras
> el re-benchmark con la topologia PCIe nueva, y el rendimiento medido hoy es
> 227.2 tok/s de prompt y 21.5 tok/s de generacion. La config vigente real esta
> en `docker-compose.glm53flash.yml`. Ver "Re-benchmark de GLM, 2026-09-11".

## Comportamiento con OpenCode (prueba end-to-end real)

- El prompt inicial de OpenCode (system + tools + AGENTS.md) es de **~9.200
  tokens**. A ~21 tok/s de prompt processing, la primera respuesta tarda
  **~7 minutos**. Es el unico punto realmente lento.
- Tras ese primer prompt, `cache_prompt` reutiliza el KV y la interaccion va
  fluida a ~15 tok/s de generacion.
- Umbral practico: ~15 tok/s es "usable para trabajo diario" y para batch
  desatendido. No llega a la comodidad de Qwen (~43) pero es funcional.

Para acortar el arranque, la palanca de software es reducir el tamano del prompt
inicial (menos tools/instrucciones). La palanca de hardware, mas efectiva, es
reemplazar los risers x1 de GPU 2/3.

## Pruebas funcionales

- API `/v1/chat/completions`: respuestas correctas, con `reasoning_content`
  separado (OpenCode lo mapea via `interleaved.field`).
- Tool calling: genera llamadas validas, acepta el resultado e incorpora la
  respuesta final sin inventar datos.
- Codigo: resolvio problemas con casos borde y asserts coherentes.
- Healthcheck y metricas operativos. Cero reinicios, `OOMKilled=false`.

## Advertencias del build

- Al cargar el GGUF, el build informa que `special_eot_id` y `special_eom_id`
  no figuran entre los EOG. No afecto las pruebas funcionales.
- Sin MTP activo, `blk.45` (la cabeza draft) aparece como tensor "unused"; es
  correcto, solo se carga con `--spec-type draft-mtp`.

## Conclusiones y trabajo futuro

1. La mejor config de generacion es **IQ1_S + auto-fit + flash-attn on + 128k**
   (~15 tok/s). Es la desplegada.
2. **MTP no ayuda** en este hardware: el cuello es el MoE en CPU/RAM, no la GPU.
3. **Mas expertos en GPU no siempre es mejor:** acelera prompt, frena generacion
   por el trafico via risers x1.
   **REFUTADO el 2026-09-11**: era un artefacto del reparto manual, que
   desperdicia VRAM. Ver "El hallazgo contraintuitivo de agosto era un
   artefacto".
4. La unica palanca de gran impacto pendiente es **reemplazar los risers de
   GPU 2/3 (Gen2 x1 -> x16)**. Eso atacaria directamente la latencia entre GPUs
   y permitiria mas expertos en GPU sin la penalizacion actual. En software ya
   se exploro casi todo el margen disponible.
   **Hecho el 2026-09-11** (quedo en Gen3 x8, no x16). Ver "Re-benchmark de
   GLM, 2026-09-11" para el resultado y las conclusiones que lo reemplazan.

## Revision 2026-09-05: mejoras de Unsloth, sin impacto

Se reviso la [guia de Unsloth](https://unsloth.ai/docs/models/glm-5.3-flash) y el
release `v0.1.806-beta` (4 de septiembre) por si resolvian el cuello de botella
de esta config. **No aplica, se descarta re-testear.**

- La mejora anunciada ("faster decoding path + MTP support, hasta 3.3x mas
  rapido") esta benchmarkeada en **1x B200 (180 GiB HBM)**, un escenario donde
  el modelo entra completo en VRAM. Es el caso GPU-bound, lo opuesto a nuestro
  setup.
- En octoserver el cuello es CPU-bound: ~34 capas de expertos MoE offloadeadas
  a RAM por falta de VRAM combinada (96 GiB en 4 GPUs, modelo ~93-109 GB sin
  contar KV/buffers). Por eso MTP ya se probo y se descarto aca (ver seccion
  "4. MTP" mas arriba): mas verificacion en paralelo no ayuda cuando el limite
  es alimentar expertos en CPU, no computo en GPU.
- El changelog no menciona ningun fix a kernels de expertos-en-CPU,
  `--n-cpu-moe`, ni latencia inter-GPU por PCIe lento (risers x1 de GPU 2/3).
  Solo agrega mejoras de tool calling en chats largos, sin relacion con
  rendimiento.
- Conclusion: la unica palanca de gran impacto sigue siendo la de siempre,
  reemplazar los risers de GPU 2/3 (Gen2 x1 -> x16). Nada de esta revision
  cambia la config vigente.

## Cambio de topologia PCIe, 2026-09-11

Se reemplazaron los risers. El cambio fue mayor que solo el ancho del enlace:
**desaparecio el switch ASM1184e** y las cuatro GPU pasaron a colgar directo de
root ports del CPU.

| Aspecto | Antes | Ahora |
|---|---|---|
| GPU 0 y 1 | Gen3 x16 | Gen3 x8 |
| GPU 2 y 3 | Gen2 x1, compartido tras ASM1184e | Gen3 x8, root port propio |
| Switch intermedio | Si | No |
| Ancho por GPU 2/3 | ~500 MB/s entre las dos | ~7.9 GB/s cada una |

Verificado bajo carga (`pcie.link.gen.current=3`, `width.current=8` en las
cuatro). En reposo ASPM las baja a 2.5GT/s, es normal.

Peer-to-peer sigue **no disponible** (`nvidia-smi topo -p2p r` = `CNS` en todos
los pares): el chipset Xeon E5 v4 no lo soporta y las 3090 no tienen NVLink
bridge. Esto no cambia con los risers.

### Re-benchmark de GLM, 2026-09-11

Metodologia identica a la usada en `docs/qwen38flash-split-benchmark.md`: prompt
fijo de 4166 tokens, 256 tokens forzados con `ignore_eos`, `temperature: 0`,
`seed: 1234`, `cache_prompt: false`, sin streaming, 3 repeticiones, TPS tomados
del objeto `timings` del server. Modelo, build e imagen sin cambios.

| Config (128k, IQ1_S) | Prompt tok/s | Generacion tok/s | Tiempo cliente | VRAM libre min. |
|---|---:|---:|---:|---:|
| auto-fit, `--fit-target 1024` (vigente) | 189.589 | 20.467 | 34.615 s | 1213 MiB |
| `n-cpu-moe 28`, split `1,1,1,1` | 30.285 | 9.995 | 163.269 s | 4351 MiB |
| auto-fit, `--fit-target 512` | **227.216** | **21.529** | **30.359 s** | 675 MiB |

Contra las mediciones de agosto (topologia vieja):

| Config | Prompt ago | Prompt sep | Generacion ago | Generacion sep |
|---|---:|---:|---:|---:|
| auto-fit | ~22 | 189.589 | ~15.4 | 20.467 |
| `n-cpu-moe 28`, split `1,1,1,1` | 36.3 | 30.285 | ~10 | 9.995 |

> **Cuidado con el prompt tok/s de agosto.** El salto de ~22 a ~190 tok/s (8.6x)
> es demasiado grande para atribuirlo solo a los risers. La carga exacta de
> agosto no quedo documentada (solo "misma carga controlada,
> `cache_prompt=false`") y ademas hoy el modelo estaba integramente en page
> cache del host. La comparacion **solida** es la de generacion, que es mucho
> menos sensible a esos factores: **+33% en auto-fit** (15.4 -> 20.5) y
> **sin cambio en la config manual** (~10 -> 10.0).

### El hallazgo contraintuitivo de agosto era un artefacto

La conclusion 3 original decia que mover mas expertos a GPU acelera el prompt
pero **frena la generacion**, y lo atribuia al trafico de activaciones por los
risers x1 de GPU 2/3. **Esa explicacion no se sostiene.** Dos evidencias:

1. La config manual (`n-cpu-moe 28`, split `1,1,1,1`) mide **igual que en
   agosto** en generacion (9.995 vs ~10 tok/s) pese a que los risers cambiaron.
   Si el cuello hubiera sido el riser x1, tendria que haber mejorado.
2. Al empujar de verdad hacia mas expertos en GPU, pero **respetando el balance
   de memoria** (auto-fit con `--fit-target 512`), mejoraron **las dos**
   metricas: +19.8% prompt y +5.2% generacion sobre el auto-fit vigente.

La causa real es que **`--tensor-split` reparte por cantidad de capas, no por
memoria**. Con `n-cpu-moe 28` los MoE de las primeras 28 capas van a CPU; las
capas que conservan sus expertos son las tardias, y en `split-mode layer` las
capas tardias caen en GPU 2 y 3. Resultado medido:

| GPU | VRAM usada | VRAM libre |
|---:|---:|---:|
| 0 | 3996 MiB | 20132 MiB |
| 1 | 2750 MiB | 21377 MiB |
| 2 | 17302 MiB | 6825 MiB |
| 3 | 19776 MiB | 4351 MiB |

GPU 0 y 1 quedan **casi vacias**: ~41 GiB de VRAM desperdiciada. Con esa VRAM
sin usar, quedan mas expertos en CPU de los necesarios, y la config se vuelve
**mas** CPU-bound, no menos. Por eso es lenta, y por eso los risers no la
ayudan: su cuello nunca fue el PCIe.

Dicho de otra forma: el auto-fit no ganaba por "balancear el trafico entre
GPUs", ganaba por **usar toda la VRAM disponible**. La leccion util no es "menos
expertos en GPU es mejor" sino "no repartir a mano con `--tensor-split`, que
ignora cuanta memoria pesa cada capa".

### Perfil de carga observado

Muestreando durante el benchmark del auto-fit vigente se ven dos fases bien
distintas:

- **Prompt processing:** las GPU pican a 76-92% de a una por vez (secuencial,
  propio de `split-mode layer`), CPU del host en 2-4%. Fase GPU-bound.
- **Generacion:** las cuatro GPU quedan parejas en 12-17% y la CPU sube a
  14-19.5%. Fase CPU-bound, consistente con el diagnostico original del
  documento.

El cuello dominante de la generacion **sigue siendo el MoE en CPU**. Lo que
cambio es que ahora se puede achicar ese tramo usando mejor la VRAM. Nota: el
sintoma descrito arriba en "El problema central" ("las GPU quedan practicamente
al 0% durante la generacion") ya no se observa; hoy es 12-17%.

### Estres de contexto largo con `--fit-target 512`

El margen de 675-769 MiB en GPU 1 y 2 es justo el escenario que provoco un OOM
en qwen38flash (ver `docs/qwen38flash-split-benchmark.md`, "Ajuste para contexto
largo"), asi que se verifico antes de recomendarlo:

| Prompt | Prompt tok/s | Generacion tok/s | Resultado |
|---:|---:|---:|---|
| 16008 | 239.86 | 17.60 | OK |
| 32008 | 223.55 | 14.08 | OK |
| 64009 | 193.85 | 10.29 | OK |
| 100008 | 165.46 | 7.80 | OK |

Sin OOM ni errores de `cudaMalloc` en ningun escalon. VRAM libre tras el estres:
2668 / 769 / 675 / 1277 MiB. La caida de generacion con el contexto (17.6 -> 7.8
tok/s) es el comportamiento esperado, no un problema de esta config.

**Limitacion de la prueba:** se llego a 100k de los 131072 tokens de contexto, no
al maximo. Un prompt cercano al tope podria comportarse distinto.

### Conclusiones actualizadas

1. Se adopta **`--fit-target 512,512,512,512`**: +19.8% prompt y +5.2%
   generacion sobre `1024`, sin OOM hasta 100k tokens. Es un parametro de entorno
   (`GLM_FIT_TARGET`), asi que volver a `1024` es inmediato si aparece un OOM.
2. **El auto-fit sigue siendo la forma correcta de repartir.** No usar
   `--n-cpu-moe` + `--tensor-split` manuales: `--tensor-split` reparte por
   cantidad de capas y desperdicia VRAM masivamente en un MoE.
3. La conclusion 3 original queda **refutada**: mas expertos en GPU si mejora la
   generacion, siempre que el reparto respete la memoria real de cada GPU.
4. La conclusion 4 original queda **cumplida y superada**: los risers ya no son
   la palanca pendiente. La palanca que queda es la de siempre, VRAM total
   (96 GiB para un modelo de ~93 GB mas KV y buffers), y esa no se resuelve con
   cableado.

### Trabajo pendiente sugerido

1. Validar `--fit-target 512` con un prompt cercano al tope de 131072 tokens (el
   estres llego a 100k).
2. Probar `--load-mode none`: el build emite `tensor overrides to CPU are used
   with mmap enabled - consider using --load-mode none for better performance`.
   No se evaluo en esta ronda.
3. Re-medir el comportamiento end-to-end con OpenCode, que es donde entra en
   juego `--cache-ram` y no lo cubre el benchmark sintetico.

No tiene sentido volver a probar `--split-mode tensor` en GLM: se descarto para
Qwen con la topologia nueva y el motivo (falta de P2P + el AllReduce interno de
llama.cpp que solo soporta 2 dispositivos) es independiente del modelo y del
cableado PCIe.

Tampoco tiene sentido volver a probar `--n-cpu-moe` + `--tensor-split` manuales:
quedo demostrado que desperdician VRAM por repartir segun cantidad de capas.

## Estado posterior

- `glm53flash`: definido en `docker-compose.glm53flash.yml`, **detenido** al
  2026-09-11. Comparte VRAM con `qwen38flash`, son mutuamente excluyentes.
- Alias / id OpenAI: `glm-5.3-flash-iq1-s` (coincide con la config de OpenCode).
- `qwen38flash`: activo y saludable en `http://octoserver.core.sied.ar:8091`.
- Ventiladores: permanecen en modo automatico.
