# DeepSeek-V4.1-Flash abliterado con Project Maya

Prueba de [Project Maya](https://github.com/mw00/project-maya) (fork de Strata + llama.cpp para MoE grandes,
motor `maya-ds4` para DeepSeek) con el DeepSeek-V4.1-Flash-1017 abliterado de orcarouter, soportado de forma
nativa por Maya desde v1.1.6x (`--ds4-quant abliterated`).

Stack: `docker-compose.maya-deepseek.yml` (proyecto propio `octofan-maya`, puerto 18090, modelo
`deepseek-v4.1-flash-abliterated`). Ocupa las cuatro GPU: **nunca a la vez que `strata-qwen` ni
`ollama`**. Desde 2026-11-16 queda encendido con **Mix-128G** (config `maya/maya-deepseek-128g.json`, default
de `MAYA_CONFIG`) y Strata parado; ver Resultados.

## Modelo

| Pieza | Origen (revision fijada en `tools/ds4/download_gguf.json` de Maya v1.1.65) | Tamano |
|---|---|---|
| Mix-128G, shards 1 y 3-5 | `orcarouter/DeepSeek-V4.1-Flash-1017-abliterated-GGUF@349470a0` (gated) | ~114 GB |
| Mix-256G, shards 1 y 3-7 | mismo repo | ~236 GB |
| Tablas Engram Q6_K | `peasantsmith/DeepSeek-V4.1-Flash-1017-Maya-GGUF@c33d87b8`, shards 4-5 de Maya-XS | 161 GB |
| Drafter DSpark | `deepseek-ai/DeepSeek-V4.1-Flash-1017@1bae0e10`, shards 44-46 | ~8 GB |
| Torre de vision | `deepseek-ai/DeepSeek-V4.1-Flash-1017@1bae0e10`, shard 1 + `config.json` | ~1 GB |

- Abliteracion de orcarouter: direccion de rechazo ortogonalizada en todas las matrices que escriben el
  residual. Su card: rechazos 0.874 -> 0.074, MMLU 0.91 -> 0.92 (no verificado aca).
- Mix-256G: expertos 2.5-4.25 bits por capa, densos Q5_K-Q8_0. Maya pide 236 GB de VRAM + RAM para
  tenerlo todo residente; el host tiene 96 + 125 = 221 GB, asi que una parte de los expertos se lee del
  SSD. Si rinde mal, la alternativa es Mix-128G (expertos ~1.6 bits, 114 GB, entra entero).
- El shard 2 de cada Mix solo trae la tabla Engram en IQ4_NL: Maya lo deja afuera y usa sus tablas Q6_K
  (`--without` en el pack).

Layout en el host (`/opt/models-archive/DeepSeek-V4.1-Flash-1017-abliterated-GGUF/`):

```text
Mix-128G/        shards GGUF + maya-ds4/ (el pack en uso)
Mix-256G/        shards GGUF + maya-ds4/
Engram-Q6_K/     tablas Engram de Maya
dspark/          shards del drafter -> dspark.bin + dspark.json
vision/          shard 1 + config.json -> vision.bin + vision.json
.logs/           scripts y logs de descarga
```

### Descarga

Lo que funciono (2026-11-16): `aria2c -x 16 -s 16` (EPEL) un archivo a la vez, ~90 MB/s, con sha256 de
cada archivo contra `tools/ds4/download_gguf.json` (`.logs/fetch-128.sh`). Las primeras descargas tiraron
el NVMe raiz del bus: no era la carga sino la **pico ATX gastada** (3,3 V a 3,0 V bajo I/O); con la pico
nueva el rail queda >= 3,15 V y aguanta escritura sostenida a 2 GB/s.

Notas previas (xet):

Con el CLI `hf` en `/opt/hf-cli` (venv propio) y el token en `/root/.cache/huggingface/token`; hay que
aceptar los terminos del repo de orcarouter con esa cuenta. Script: `.logs/fetch-all.sh`.

- **xet sin limite casi deja al host sin RAM**: dos `hf download` en paralelo (uno con
  `HF_XET_HIGH_PERFORMANCE=1`) llegaron a 11 + 18 GB de RSS y el host quedo con 5 GB disponibles, con
  Strata arriba. Bajar de a un proceso, sin high performance, con
  `systemd-run --scope -p MemoryMax=10G` y `HF_XET_NUM_CONCURRENT_RANGE_GETS=8`: ~90 MB/s y <1 GB de RSS.
- Sin xet (`HF_HUB_DISABLE_XET=1`) el CLI se niega a bajar archivos grandes.
- `hf download repo --include a b` toma `b` como nombre de archivo e ignora `--include`: pasar los
  archivos como posicionales.

## Imagen

No hay imagen oficial. Se construye en el host con la receta de Maya (`docs/DOCKER.md`), solo sm_86 y con
pocos jobs para no quitarle RAM a Strata (nvcc usa 2-4 GB por job):

```bash
cd /opt/project-maya && git checkout v1.1.65
docker/build.sh --ref v1.1.65 --cuda 13 --archs "86" --jobs 6   # -> project-maya:1.1.65-cuda13
```

La imagen trae los motores compilados, el server y los empaquetadores, pero **no corre el setup** de Maya
(pide `nvcc`). El pack y la config (`maya/maya-deepseek.json`, con rutas del container) se arman a mano,
replicando `pack_step` y `write_config_ds4` de `maya.py`.

## Pack

Con el stack parado, en el mismo container:

```bash
cd /opt/ia-octo-server
R="docker compose -f docker-compose.maya-deepseek.yml run --rm --no-deps maya-deepseek /opt/maya/.venv/bin/python"
$R /opt/maya/tools/ds4/drafter_pack.py --dir /models/dspark
$R /opt/maya/tools/ds4/vision_pack.py --dir /models/vision
$R /opt/maya/tools/ds4/pack_gguf.py --model /models/Mix-256G --out /models/Mix-256G/maya-ds4 \
  --engram /models/Engram-Q6_K --drafter /models/dspark/dspark.json --vision /models/vision \
  --shards DeepSeek-V4.1-Flash-1017-abliterated-Mix-256G-0000{1,3,4,5,6,7}-of-00007.gguf \
  --without DeepSeek-V4.1-Flash-1017-abliterated-Mix-256G-00002-of-00007.gguf
# Mix-128G: igual con --model /models/Mix-128G --out /models/Mix-128G/maya-ds4,
#   --shards ...Mix-128G-0000{1,3,4,5}-of-00005.gguf --without ...Mix-128G-00002-of-00005.gguf
```

## Config

`maya/maya-deepseek.json`: `--max-context 1048576` (maximo nativo, `max_position_embeddings`),
`--tp 2` (dos pares de 3090; no necesita P2P), vision activa (el pack trae la torre), `--dspark none`
hasta medir si el drafting conviene, sampling de DeepSeek (`temperature 1.0`, `top_p 1.0`, esfuerzo `high`).

## Ventana de prueba

1. Respaldar `config/octofan.yaml`; `PUT /api/config` con `ai_recovery_enabled: false` y
   `gpu_recovery_restart_containers: []` (si no, el watchdog vuelve a arrancar Strata).
2. `docker compose -f docker-compose.strata-qwen.yml stop` y `docker compose -f docker-compose.flux.yml stop`.
3. `docker compose -f docker-compose.maya-deepseek.yml up -d` y esperar `healthy` (la primera carga tarda).
4. Medir con `scripts/bench-openai-timings.py` contra `http://localhost:18090/v1`.
5. Volver a Strata: `docker compose -f docker-compose.maya-deepseek.yml down`, levantar Strata y Flux con
   su `-f`, restaurar `config/octofan.yaml` (`strata.base_url` a `:18080`, recovery a `strata-qwen`) y
   verificar fans en `auto` y Strata `1/1 loaded`.

## Resultados (2026-11-16, Maya v1.1.65, 4x RTX 3090 a 250 W, `scripts/bench-openai-timings.py`)

| Caso | Mix-256G prompt / gen (tok/s) | **Mix-128G** prompt / gen (tok/s) | Strata Qwen (ref.) |
|---|---|---|---|
| short (256 tok, 3 reps) | 7,7-10,4 / 9,7 -> 25,0 | 60-87 / 38,7 -> 50,6 | |
| code (1024 tok) | 13-15 / 17,5-23,0 | 97-137 / 44,4-46,7 | |
| long8k (8,5k prompt) | **237** / 14,6 | **1008** / 43,5 | ~990 / ~105 |

- Mix-256G (236 GB) no entra en 96 GB VRAM + 125 GB RAM: lee expertos del SSD, arranca a ~6 tok/s en frio
  y no pasa de ~25. Mix-128G entra entero y da los numeros que publica Maya.
- Carga del modelo: ~80 s. Contexto 1048576, vision activa (describe bien una imagen de prueba), drafter
  DSpark aceptando ~50 % con Mix-128G.
- Calidad rapida Mix-128G: razonamiento aritmetico correcto; la abliteracion funciona (pedidos vulgares
  o de ganzuas se responden). Piensa largo: ~3,6k tokens de razonamiento aun con `reasoning_effort: low`,
  dar `max_tokens` holgado.
- Decision: queda **Mix-128G encendido** como servicio (Strata parado, `unless-stopped` respeta el stop).
  El controller lo monitorea por `strata.base_url` -> `:18090` y la AI recovery reinicia `maya-deepseek`.
  Mix-256G queda en disco (`MAYA_CONFIG=maya-deepseek.json`).
