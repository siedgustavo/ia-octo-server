# Benchmark de split multi-GPU para Qwen3.8-Flash-Next

Comparacion de `tensor` y `layer` sobre el servidor de produccion. El objetivo es
medir el impacto de la topologia PCIe real usando exactamente el mismo modelo,
build y carga en ambos modos.

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

## Criterio de comparacion

Se compararan por separado los promedios de prompt processing y generacion. La
decision final tambien debe considerar estabilidad, errores de arranque,
distribucion de VRAM y comportamiento con contexto largo; no solo el mayor TPS
de una unica repeticion.
