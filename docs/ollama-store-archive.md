# Archivo frío del store de Ollama en inference2

**Fecha:** 2026-11-16/17 (copia iniciada 23:48 local del 16, terminó 02:20 local del 17).
**Alcance:** sólo el store de modelos de Ollama (`/opt/ollama/models`). Los modelos de
Strata/Maya (`/opt/models-archive`) quedan en octoserver para una fase posterior.

## Qué se movió y por qué

El store real de Ollama estaba en `/opt/ollama/models` y ocupaba **399 GiB** físicos
(428,38 GB lógicos por blobs compartidos). `octofan-ollama` está detenido desde hace dos
semanas como fallback, así que el store quedó frío mientras Strata/Maya y Flux ocupan los
servicios. El disco raíz de octoserver estaba al **90 %** (197 GB libres); después de la
verificación y del borrado del origen quedó **69 % usado / 584 GB libres**.

Destino: `/mnt/raid1hdd/archive/ollama/models` en `inference2.core.sied.ar`:

- `md127`, RAID1 de 5,5 TB (2× WD60EFAX SMR), XFS con `noatime,nofail` sobre `/mnt/raid1hdd`.
- Después de la copia: 5,0 TB libres (9 % usado). El `tl-node` torrent y sus descargas
  siguen en el mismo RAID1, intactos.
- El RAID1 es un espejo local, **no un backup remoto**; si se quiere respaldo de verdad,
  replicar el archive al NAS/Synology.

## Contenido

51 archivos (33 blobs, 7 manifests, 11 metadata):

```text
ollama/models/
├── blobs/     (sha256-...)
├── manifests/ (registry.ollama.ai/library/...)
└── metadata/  (sha256-...json)
```

Tags archivados:

| Tag | Blobs |
|---|---|
| `gpt-oss:120b` | 65,4 G |
| `mistral-medium-3.5:128b` | 39,7 G |
| `qwen3-coder-next:80b` | 51,7 G |
| `qwen3.8:27b-q8_0` | 30,0 G |
| `qwen3.8-uncensored:27b` | 16,6 G |
| `qwen3.8-flash-next:176b` | 112,2 G |
| `qwen3.8-flash-next-uncensored:176b` | 112,7 G |

## Procedimiento usado

Copie directa octoserver → inference2 con agent forwarding de la clave local del `.30`
(ambos hosts la autorizan), sin relay y sin password en el host:

```bash
rsync -aHAX --numeric-ids --whole-file --partial --info=progress2 --stats --bwlimit=60M \
  -e "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
  /opt/ollama/models/ \
  root@inference2:/mnt/raid1hdd/archive/ollama/models/.staging/
```

Se hizo bajo `ionice -c2 -n7 nice -n19`; **no se pausaron** `tl-node-qbittorrent-1` ni
`tl-node-autobrr-1`. Resultado del rsync: 428,38 GB lógicos enviados a 46,89 MB/s
promedio en 2h32m; destino físico 399 GiB (los hardlinks de blobs se preservaron).
La verificación de integridad comparó hashes sha256 del contenido contra el nombre
`sha256-...` de cada blob, y manifiestos/metadata byte a byte. Resultado final
(2026-11-17 05:23:55–06:05:12 UTC): **33/33 blobs OK, `bad=0`**, listado/tamaños
idénticos y manifiestos/metadata coincidentes. Con eso se borró `/opt/ollama/models`
de octoserver; sólo quedó el directorio `/opt/ollama` con cache/historial/claves.

Logs y evidencia: `sysadmin/dumps/2026-11-16/model-archive-ollama/` (copia, listado
y verificación).

## Restauración

Si hay que volver a usar Ollama en octoserver:

1. Parar Maya/Strata/Flux (comparten las 4 GPU y la mayor parte de la RAM; el perfil
   `ollama` es fallback y `docker compose up -d` no lo levanta solo).
2. Reponer el store desde inference2 a `/opt/ollama/models` (directo con agent
   forwarding o relay por `.30`):
   ```bash
   ionice -c2 -n7 nice -n19 rsync -aHAX --numeric-ids --whole-file --partial --info=progress2 \
     -e "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
     root@inference2:/mnt/raid1hdd/archive/ollama/models/ \
     /opt/ollama/models/
   ```
3. Confirmar el store y levantar el nodo:
   ```bash
   docker compose --profile ollama up -d ollama   # o docker start octofan-ollama
   docker exec octofan-ollama ollama list
   ```
   `OLLAMA_DATA_DIR` sigue siendo `/opt/ollama`; las claves/historial/cache quedaron
   en octoserver, sólo se movió `models/`.

Si se quiere servir el archive sin reponerlo en octoserver, hacerlo como **frío**: no
montar `/mnt/raid1hdd` por red en octoserver para servir modelos; los GGUF a 1 GbE y
RAID1 SMR no alcanzan la velocidad que necesita llama.cpp.

## Fase pendiente

La segunda fase ya ejecutada archiva los GLM en `/mnt/raid1hdd/archive/models-archive`
(ver [GLM models archive](glm-models-archive.md)); la fase 3 archiva los coder legacy de
`/opt/llamacpp/models` en `/mnt/raid1hdd/archive/llamacpp/models`
(ver [llama.cpp models archive](llamacpp-models-archive.md)). Queda pendiente el resto de
`/opt/models-archive` (`UD-Q4_K_XL`, `Qwen3.8-Flash-Next-Uncensored-Q4_K_S`, MTP).
No se tocó `DeepSeek-V4.1-Flash-1017-abliterated-GGUF` (Maya),
`Huihui-Qwen38-abliterated-v2-UD-Q4_K_XL` (Strata) ni `/opt/strata-test`.
