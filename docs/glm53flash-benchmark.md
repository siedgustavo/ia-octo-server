# GLM-5.3-Flash en el Octoserver: tuning y lecciones

Registro completo de la puesta a punto de GLM-5.3-Flash sobre las cuatro
RTX 3090 del Octoserver, usando llama.cpp con el soporte GLM-5-Next de Unsloth.
La instancia reemplaza temporalmente al servicio Qwen3.8-Flash-Next y queda
expuesta como API compatible con OpenAI en el puerto 8090.

Este documento consolida varias iteraciones de prueba. La configuracion vigente
esta al final, en "Configuracion final desplegada".

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
| Generacion medida | ~43 tok/s | ~15 tok/s |

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
4. La unica palanca de gran impacto pendiente es **reemplazar los risers de
   GPU 2/3 (Gen2 x1 -> x16)**. Eso atacaria directamente la latencia entre GPUs
   y permitiria mas expertos en GPU sin la penalizacion actual. En software ya
   se exploro casi todo el margen disponible.

## Estado posterior

- `glm53flash`: activo y saludable en `http://octoserver.core.sied.ar:8090`,
  levantado por `docker-compose.glm53flash.yml`.
- Alias / id OpenAI: `glm-5.3-flash-iq1-s` (coincide con la config de OpenCode).
- `qwen38flash`: detenido limpiamente para liberar sus GPU (recuperable).
- Ventiladores: permanecen en modo automatico.
