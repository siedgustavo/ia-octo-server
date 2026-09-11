# Octoserver vs NVIDIA DGX Spark

Comparacion del stack Octofan (4x RTX 3090 en un gabinete Octominer) contra el
NVIDIA DGX Spark, usando **el mismo modelo** (`gpt-oss-120b`, MXFP4) como punto
de anclaje.

- Fecha: 2026-09-11 (America/Argentina/Buenos_Aires)
- Host: `octoserver.core.sied.ar`
- Topologia PCIe: la nueva (4x Gen3 x8 directo a root ports, ver
  `docs/qwen38flash-split-benchmark.md`)

## Por que gpt-oss-120b

Ningun modelo de produccion del Octoserver (Qwen3.8-Flash-Next, GLM-5.3-Flash)
aparece en los benchmarks publicos de DGX Spark, y ninguno de los modelos de esos
benchmarks estaba desplegado aca. `gpt-oss-120b` es el unico solapamiento util:

- Esta en el benchmark oficial de llama.cpp para DGX Spark.
- Ya estaba descargado en el Ollama del Octoserver (`gpt-oss:120b`).
- Con 116.83B parametros MoE en MXFP4 entra completo en los 96 GiB de VRAM, sin
  offload a CPU, asi que mide la maquina y no el cuello del PCIe/RAM.

Comparar los numeros de Qwen3.8-Flash-Next contra los de gpt-oss-120b del Spark
seria comparar dos modelos distintos y no dice nada. Por eso no se hace.

## Hardware

| | Octoserver | DGX Spark |
|---|---|---|
| Computo | 4x RTX 3090 (Ampere GA102, sm_86) | GB10 Grace Blackwell (sm_121) |
| Memoria para el modelo | 96 GiB GDDR6X (4x24) | 128 GB LPDDR5x unificada |
| Ancho de banda | 936 GB/s **por GPU** | 273 GB/s total |
| Bus de memoria | 384-bit por GPU | 256-bit |
| CPU | 2x Xeon E5-2680 v4 (28c/56t), sin AVX-512 | 20 cores ARM (10x X925 + 10x A725) |
| RAM del host | 125 GiB DDR4 | unificada con la GPU |
| Interconexion GPU-GPU | PCIe Gen3 x8, **sin P2P** | N/A (chip unico) |
| FP4 en hardware | no (Ampere) | si (Blackwell, NVFP4/MXFP4) |
| Consumo del sistema | ver "Consumo" | ~240 W (fuente) |

La diferencia estructural: el Octoserver tiene **3.4x mas ancho de banda** en la
GPU activa, pero **menos capacidad** y la memoria esta fragmentada en cuatro
islas sin P2P. El Spark tiene un pool unico de 128 GB, mas lento pero contiguo.

## Metodologia y sus limites

**Esta comparacion no es apples-to-apples perfecto.** Las diferencias, explicitas:

| | Octoserver (esta medicion) | DGX Spark (referencia) |
|---|---|---|
| Motor | Ollama | llama.cpp (`llama-bench`) |
| Build | Ollama del stack | llama.cpp build 7941 |
| GGUF | conversion de Ollama, 60.88 GiB | `ggml-org/gpt-oss-120b-GGUF`, 59.02 GiB |
| Medicion de prompt | prompt real de N tokens | `pp2048` a profundidad `-d` |
| Generacion | 32 tokens, `temperature 0`, `seed 1234` | `tg32` |

Se intento correr `llama-bench` directamente contra el blob de Ollama para
eliminar la variable del motor, pero **no se pudo**: el GGUF de Ollama declara la
arquitectura `gptoss`, que llama.cpp upstream no reconoce
(`unknown model architecture: 'gptoss'`). Es una conversion propia de Ollama, no
el GGUF de ggml-org (de ahi tambien la diferencia de tamano, 60.88 vs 59.02 GiB).

Consecuencias para leer los resultados:

- **La generacion es razonablemente comparable.** Es memory-bandwidth-bound y
  poco sensible al motor. Es la metrica en la que apoyar conclusiones.
- **El prompt processing NO es comparable de forma directa.** `llama-bench` mide
  `pp2048` con un KV previo de profundidad `-d`; aca se procesan prompts enteros
  de largo creciente, que amortizan el overhead de otra forma (por eso el tok/s
  *sube* con el largo en la tabla de abajo, al reves que en el bench oficial).
  Las columnas de prompt estan para referencia, no para sacar un ratio.

Fuente de los numeros de DGX Spark:
[ggml-org/llama.cpp, benches/dgx-spark](https://github.com/ggml-org/llama.cpp/blob/master/benches/dgx-spark/dgx-spark.md)
(build 7941, driver 580.95.05, CUDA 13.0).

## Resultados

### Octoserver, gpt-oss:120b en Ollama, 100% en GPU

Confirmado sin offload: `size=66.51 GB`, `size_vram=66.51 GB`. VRAM usada
15.4-17.7 GiB por GPU, 3 repeticiones por fila.

| Prompt tokens | Prompt tok/s | Generacion tok/s |
|---:|---:|---:|
| 2064 | 2027.56 | **104.04** |
| 4112 | 4528.10 | **107.24** |
| 8209 | 6021.50 | **102.39** |
| 16400 | 7143.77 | **92.61** |
| 32785 | 5906.38 | **77.08** |

### DGX Spark, gpt-oss-120b, llama.cpp oficial

| Profundidad | pp2048 tok/s | tg32 tok/s |
|---:|---:|---:|
| 0 | 2443.91 | **58.72** |
| 4096 | 2309.84 | **55.67** |
| 8192 | 2216.68 | **52.87** |
| 16384 | 1956.31 | **49.45** |
| 32768 | 1567.08 | **42.76** |

### Generacion, lado a lado

| Contexto aprox. | Octoserver | DGX Spark | Ventaja Octoserver |
|---:|---:|---:|---:|
| ~2k | 104.04 | 58.72 | **1.77x** |
| ~4k | 107.24 | 55.67 | **1.93x** |
| ~8k | 102.39 | 52.87 | **1.94x** |
| ~16k | 92.61 | 49.45 | **1.87x** |
| ~32k | 77.08 | 42.76 | **1.80x** |

El Octoserver genera entre **1.77x y 1.94x** mas rapido, de forma consistente en
todo el rango de contexto. La ventaja no llega al 3.4x que sugiere el ancho de
banda bruto, lo cual es esperable: en `split-mode layer` cada token recorre las
cuatro GPU en secuencia, y esos saltos (sin P2P) no aportan ancho de banda, solo
latencia.

## Consumo

Medido en las PSU del gabinete via PSMI (`octofan_psu_metric{metric="power_ac"}`)
y en las GPU via `nvidia-smi`.

| Estado | AC (PSUs) | GPU (`nvidia-smi`, suma de 4) |
|---|---:|---:|
| Idle con modelo cargado | 232 W | 105 W |
| Carga sostenida, mediana | 245 W | 458 W |
| Carga sostenida, p90 | 843 W | - |
| Pico | 1377 W | 927 W |

La mediana AC baja (245 W) esta sesgada por los huecos entre requests del
muestreo; el p90 de 843 W representa mejor el consumo durante trabajo real.

Contra los ~240 W del Spark (fuente del sistema completo):

| | Octoserver | DGX Spark |
|---|---:|---:|
| Generacion (@~2k ctx) | 104.04 tok/s | 58.72 tok/s |
| Consumo bajo carga | ~843 W (p90 AC) | ~240 W |
| **Tokens por watt** | **0.123** | **0.245** |

**El Spark es ~2x mas eficiente por watt, el Octoserver es ~1.8x mas rapido en
absoluto.** Es el trade-off central de la comparacion.

## Lectura

### Donde gana el Octoserver

- **Generacion pura**, 1.8-1.9x, para cualquier modelo que entre en 96 GiB.
- **Costo de hardware**: son GPU de mineria recicladas en un gabinete que ya
  existia, contra un equipo nuevo de gama alta.
- **Flexibilidad**: 4 GPU discretas permiten repartir servicios, y el host tiene
  125 GiB de RAM DDR4 para offload de MoE grandes (aunque a un costo alto de
  rendimiento, ver `docs/glm53flash-benchmark.md`).

### Donde gana el Spark

- **Eficiencia energetica**, ~2x tokens por watt. En uso continuo la diferencia
  de factura electrica es real.
- **Capacidad contigua**: 128 GB unificados contra 96 GiB fragmentados en cuatro
  islas de 24 GiB sin P2P. Esta es la diferencia mas importante para este stack.
- **FP4 en hardware** y un stack de software soportado por NVIDIA.
- Ruido, tamano, calor y complejidad operativa incomparablemente menores.

### El punto que mas importa para este stack

GLM-5.3-Flash pesa ~93 GB en IQ1_S. **No entra** en 96 GiB junto con KV cache y
buffers, asi que ~34 capas de expertos MoE quedan en RAM del host y la generacion
cae a ~21.5 tok/s (ver `docs/glm53flash-benchmark.md`). En 128 GB unificados
entraria completo, sin offload.

Es decir: en el rango de modelos de 96-128 GB, la ventaja de 1.8x en ancho de
banda del Octoserver **se pierde por completo**, porque pasa a competir con el
cuello de la CPU en vez de con la memoria. Para modelos que entran (Qwen3.8-Flash
-Next, gpt-oss-120b) el Octoserver gana comodo; para los que no, el Spark
probablemente gane a pesar de su memoria mas lenta.

**No se midio esa hipotesis**, porque requeriria un DGX Spark. Queda anotada como
lo que es: un razonamiento apoyado en las mediciones de ambos cuellos, no un dato.

## Trabajo pendiente

1. Repetir la medicion del Octoserver con `llama-bench` y el GGUF de ggml-org
   para eliminar las dos variables de confusion (motor y conversion del modelo).
   Requiere descargar 59.02 GiB.
2. Medir el consumo AC con un muestreo continuo durante carga sostenida, sin
   huecos, para tener una media limpia en vez de un p90.
