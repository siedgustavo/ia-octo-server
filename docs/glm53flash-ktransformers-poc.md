# GLM-5.3-Flash con ktransformers en el Octoserver: POC y veredicto

Registro del intento de correr GLM-5.3-Flash sobre ktransformers (kt-kernel +
SGLang-KT) en el Octoserver, con el objetivo de jugar con la "plantilla de
expertos" (CPU-GPU Expert Scheduling: expertos calientes a VRAM, frios a RAM).

**Veredicto corto: NO es viable en este hardware reutilizando los GGUF que ya
tenemos.** El stack de ktransformers compila y arranca en el Octoserver, pero
GLM-5-Next exige el backend FP8 para el offload de expertos y prohibe
explicitamente el backend GGUF/LLAMAFILE, que era justo el unico que encajaba
con esta CPU y esta RAM.

## Entorno

- Fecha: 2026-09-07 (America/Argentina/Buenos_Aires)
- Host: `octoserver.core.sied.ar`
- Contenedor POC: `kt-poc`, base `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04`
- Python 3.12, venv en `/opt/venv`
- Paquetes: `torch 2.9.1+cu128`, `kt-kernel 0.7.0.post2`, `sglang-kt 0.7.0.post3`,
  `sgl-kernel 0.3.19`
- Hardware: 4x RTX 3090 (SM86), 2x Xeon E5-2680 v4 (28 cores / 56 threads,
  2 NUMA nodes, **AVX2 sin AVX-512/AMX**), 125 GiB RAM (0 swap)
- GGUF disponibles (Unsloth, en `/opt/models-archive`):
  - `GLM-5.3-Flash-UD-IQ1_S` (87 GB, 3 shards)
  - `GLM-5.3-Flash-UD-Q2_K_XL` (102 GB, 4 shards)

Referencias:

- [ktransformers](https://github.com/kvcache-ai/ktransformers)
- [Tutorial GLM-5.3-Flash (kt)](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/kt-kernel/GLM-5.3-Flash-Tutorial.md)
- [CPU-GPU Expert Scheduling](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/kt-kernel/experts-sched-Tutorial.md)
- [kt-kernel README (backends)](https://github.com/kvcache-ai/ktransformers/blob/main/kt-kernel/README.md)

## Lo que SI funciono (el stack corre en este hardware)

El POC probo, paso a paso, que ktransformers es instalable y arranca en el
Octoserver a pesar de ser hardware viejo:

1. **kt-kernel elige el backend AVX2 solo.** `kt doctor` y
   `kt_kernel.__cpu_variant__` reportan `avx2`. La auto-deteccion cae al kernel
   de maxima compatibilidad sin pedir AVX-512/AMX. 28 cores y 2 NUMA nodes bien
   detectados.
2. **sgl-kernel carga en SM86 via PTX JIT.** El wheel `sgl-kernel 0.3.19` solo
   trae binarios `sm90` y `sm100` (no `sm86`). Su loader mapea toda CC != 90 al
   build `sm100` ("precise math for compatibility"), que incluye PTX y JITea a
   SM86. Verificado: `common_ops` carga y un kernel real ejecuta en la 3090.
   - Ojo: el `sglang-kt` de PyPI arrastra por defecto un `sgl-kernel` basado en
     "payloads" que **solo** trae `sm100` (Blackwell). Hay que forzar
     `pip install --no-deps sgl-kernel==0.3.19` para tener tambien `sm90` y el
     loader con fallback PTX. Sin eso: `ImportError: Could not load any
     common_ops library` en SM86.
3. **SGLang-KT parsea y tiene perfil GPU para la 3090.** Con `--kt-method FP8`,
   `prepare_server_args` pasa e imprime:
   `Set GLM-5-Next GPU profile=sm86_bf16, KV cache=bfloat16 ... kernels on
   SM86/SM89/SM120`. **El lado GPU soporta Ampere/3090.** El cuello no es la GPU.

## Donde se rompe (el gate)

El objetivo era usar el backend **LLAMAFILE** (expertos de CPU leidos directo
del GGUF, solo requiere AVX2, RAM = tamano del GGUF). Al lanzar con
`--kt-method LLAMAFILE`, SGLang-KT aborta en la validacion de argumentos:

```
ValueError: GLM-5-Next Session AB KT expert offload requires --kt-method FP8
so the block-E4M3 checkpoint layout is preserved and swiglu_limit reaches the
CPU expert kernel; got 'LLAMAFILE'.
```

Es una **prohibicion hardcodeada**: el offload de expertos de GLM-5-Next solo
esta implementado sobre el layout FP8 block-E4M3. GGUF/LLAMAFILE no es opcion
para esta arquitectura (a diferencia de Qwen3/Kimi, que si lo aceptan).

Antes de ese error hubo otro esperado: SGLang necesita la metadata HF, no solo
el GGUF.

```
RuntimeError: SGLANG_APPLY_CONFIG_BACKUP=auto requires the checkpoint's
config.json at .../GLM-5.3-Flash-UD-IQ1_S/config.json to read num_hidden_layers.
```

Se resolvio bajando solo los archivos chicos de `zai-org/GLM-5.3-Flash`
(`config.json`, `tokenizer*`, `generation_config.json`, ~20 MB) y apuntando
`--model` a ese dir. Con eso el gate avanza hasta el `ValueError` de arriba.
El arch declarado es `Glm5NextForConditionalGeneration` (config) / `glm5next`
(GGUF).

## Por que el path FP8 tampoco sirve aca

`--kt-method FP8` pasa la validacion, pero cargar de verdad es imposible en este
host, por tres razones independientes:

| Requisito FP8 de GLM-5.3-Flash | Octoserver | Estado |
|---|---|---|
| Checkpoint FP8 block-E4M3 (~306 GiB) | solo tenemos GGUF cuantizado | falta |
| RAM para expertos FP8 en CPU (>=350 GB) | 125 GiB | insuficiente |
| Kernel FP8 CPU (AVX512F+BW+BF16+VBMI) | Broadwell, AVX2 solo | no cumple |

Es decir: el unico backend que encajaba con la CPU/RAM (LLAMAFILE/GGUF) esta
prohibido para GLM-5-Next, y el unico permitido (FP8) no entra ni en RAM ni en
el set de instrucciones de la CPU, y ademas requeriria descargar 306 GiB que no
tenemos.

## Respuesta a "podemos reutilizar el GGUF que ya tengo?"

**No, para GLM-5.3-Flash sobre ktransformers.** Los GGUF de Unsloth (IQ1_S/
Q2_K_XL) solo sirven al backend LLAMAFILE, que GLM-5-Next rechaza. ktransformers
para este modelo pide el checkpoint FP8 oficial (~306 GiB), que no cabe en los
125 GiB de RAM y cuyo kernel de CPU necesita AVX-512, ausente en el Xeon E5-2680
v4.

Los GGUF que ya tenemos siguen siendo utiles: son los que corren hoy en
**llama.cpp** (servicio `glm53flash`, puerto 8090), donde el offload de expertos
a CPU/RAM si funciona sobre AVX2. Ese sigue siendo el unico camino real para
GLM-5.3-Flash en este hardware.

## Que haria falta para retomar esto

- **CPU con AVX-512 (idealmente AMX)** y **>=350 GB RAM** para el path FP8, o
- que ktransformers agregue soporte **LLAMAFILE/GGUF para GLM-5-Next** (hoy
  prohibido por diseno), o
- un checkpoint FP8 mas chico de GLM-5-Next que entre en RAM (no existe hoy).

Para jugar con la plantilla de expertos de ktransformers *como feature* sin
cambiar hardware, el candidato realista es un MoE soportado por LLAMAFILE
(ej. Qwen3-Next-80B), no GLM-5.3-Flash. Quedo fuera de alcance de este POC por
decision de no descargar modelos nuevos.

## Estado tras el POC

- Contenedor `kt-poc` eliminado; imagen base CUDA queda cacheada en el host.
- `/opt/models-archive` intacto (se monto read-only; la metadata HF se bajo
  dentro del contenedor efimero, ya borrada).
- `qwen38flash` relevantado desde `docker-compose.qwen38flash.yml`; su KV cache
  del slot 0 se habia persistido en el `down` limpio.
- Ventiladores en modo automatico (fan_control calcula target por temperatura,
  reason "intake"), sin fail-safe.
</content>
</invoke>
