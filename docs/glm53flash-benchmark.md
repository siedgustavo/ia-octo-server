# Prueba dedicada de GLM-5.3-Flash UD-Q2_K_XL

Prueba de GLM-5.3-Flash sobre las cuatro RTX 3090 del Octoserver, usando el
soporte de llama.cpp desarrollado en el PR de Unsloth. La instancia reemplaza
temporalmente al servicio Qwen3.8-Flash-Next y queda expuesta como API compatible
con OpenAI en el puerto 8090.

## Entorno

- Fecha: 2026-08-29 (America/Argentina/Buenos_Aires)
- Host: `octoserver.core.sied.ar`
- llama.cpp: `0.3.0-dev`, build `10667`, commit `2e0e57f10`
- Soporte GLM-5-Next: PR `ggml-org/llama.cpp#27754` de Unsloth
- Imagen CUDA: CUDA 12.6.3, compilada especificamente para Ampere `sm_86`
- Modelo: `GLM-5.3-Flash-UD-Q2_K_XL`, cuatro shards, aproximadamente 109 GB
- Hardware: 4x RTX 3090 de 24 GiB
- CPU: 2x Xeon E5-2680 v4, 28 cores y 56 threads en total
- GPU 0 y 1: PCIe x16
- GPU 2 y 3: PCIe x1, detras de risers

Referencias:

- [Guia GLM-5.3-Flash de Unsloth](https://unsloth.ai/docs/models/glm-5.3-flash)
- [PR 27754 de llama.cpp](https://github.com/ggml-org/llama.cpp/pull/27754)

## Configuracion elegida

```text
--split-mode layer
--n-gpu-layers 999
--tensor-split 1.6,1.6,0.4,0.4
--n-cpu-moe 34
--load-mode none
--ctx-size 262144
--parallel 1
--batch-size 512
--ubatch-size 128
--flash-attn off
--temp 1.0
--top-p 0.95
```

Tambien se fija `NVIDIA_TF32_OVERRIDE=0`. Tanto esa variable como Flash
Attention deshabilitado son requisitos de correccion indicados por el PR. El
contexto nativo declarado por el modelo es mayor, pero para esta instancia se
eligieron explicitamente los mismos 262144 tokens que usa Qwen.

El modelo no entra completo en los 96 GiB de VRAM. `--n-cpu-moe 34` mantiene
parte de los expertos MoE en RAM y deja el siguiente reparto en reposo:

| GPU | VRAM usada | VRAM libre aproximada |
|---:|---:|---:|
| 0 | 13984 MiB | 10144 MiB |
| 1 | 22926 MiB | 1201 MiB |
| 2 | 21822 MiB | 2305 MiB |
| 3 | 15476 MiB | 8651 MiB |

No se redujo mas `n-cpu-moe`: GPU 1 ya queda con solo 1,2 GiB libres y conviene
conservar margen para buffers temporales y contexto largo.

## Rendimiento

Primero se uso una carga corta, identica antes y despues de mover cuatro capas
MoE adicionales desde CPU hacia GPU:

| Configuracion | Prompt | Prompt tok/s | Salida | Generacion tok/s | Tiempo cliente |
|---|---:|---:|---:|---:|---:|
| `n-cpu-moe 38` | 518 | 30.921 | 128 | 6.281 | 36.975 s |
| `n-cpu-moe 34` | 518 | 34.064 | 128 | 7.314 | 32.584 s |

El ajuste final mejoro aproximadamente 10% el procesamiento del prompt y 16%
la generacion.

La carga controlada mas larga uso 4177 tokens de prompt, 256 tokens de salida,
`seed 1234`, `cache_prompt=false` e `ignore_eos=true`:

| Prompt tok/s | Generacion tok/s | Tiempo cliente |
|---:|---:|---:|
| 41.029 | 6.540 | 141.184 s |

Durante esa carga las GPU consumieron entre aproximadamente 109 W y 142 W, sin
thermal throttling. La utilizacion SM instantanea fue baja, con picos cercanos a
13%, mientras el host sostuvo alrededor de 29 hilos ejecutables y 39-41% de CPU
de usuario agregado. El limite actual es el tramo MoE descargado en CPU/RAM y la
coordinacion entre capas/dispositivos; no la temperatura ni la capacidad de
calculo bruta de las RTX 3090. Los risers x1 siguen condicionando el reparto,
pero no aparecio trafico PCIe sostenido alto durante esta muestra.

## Pruebas funcionales

- API `/v1/chat/completions`: respuesta correcta con reasoning `low`.
- Tool calling: genero una llamada valida a `get_rack_temperature`, acepto el
  resultado simulado y lo incorporo correctamente a la respuesta final.
- Codigo: resolvio `merge_intervals` en Python con complejidad O(n log n), sin
  mutar la entrada, y paso casos vacios, desordenados y con intervalos contiguos.
- Healthcheck y metricas: `/health` y `/metrics` operativos.
- Estabilidad: cero reinicios y `OOMKilled=false` despues de las pruebas.

No se lleno el contexto completo de 262144 tokens en esta sesion de benchmark;
ese caso queda pendiente para una prueba prolongada con una carga real.

## Advertencias del build experimental

El PR permanece experimental. Al cargar este GGUF, el build fijado informa que
`special_eot_id` y `special_eom_id` no figuran entre los EOG y omite los tensores
adicionales `blk.45`, incluidos los de `nextn`. Las respuestas, tool calling y
pruebas de codigo funcionaron correctamente, pero conviene repetir la validacion
cuando se actualice al head definitivo del PR.

## Estado posterior

- `glm53flash`: activo y saludable en `http://octoserver.core.sied.ar:8090`.
- Alias OpenAI: `glm-5.3-flash`.
- `qwen38flash`: detenido limpiamente para liberar sus GPU.
- Ventiladores: permanecen en modo automatico.
