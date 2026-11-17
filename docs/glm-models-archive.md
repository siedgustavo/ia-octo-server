# Archivo frío de modelos GLM en inference2

**Fecha:** 2026-11-17 (copia terminada 17:08:49 UTC; verificación 17:10:51–17:34:37 UTC).
**Alcance:** todos los modelos GLM-5.3-Flash que estaban en `/opt/models-archive`, porque
`glm53flash` no está en uso. Los modelos de Maya/Strata quedan calientes.

## Qué se movió

Origen: `/opt/models-archive` en `octoserver.core.sied.ar`:

| Carpeta | Disco físico | Archivos |
|---|---:|---|
| `GLM-5.3-Flash-UD-IQ1_S` | 87 GiB | 3 GGUF (3 shards) |
| `GLM-5.3-Flash-UD-IQ1_S-upstream` | 9 MB | 1 (upstream) |
| `GLM-5.3-Flash-UD-Q2_K_XL` | 102 GiB | 4 GGUF (4 shards) |

Destino: `/mnt/raid1hdd/archive/models-archive/` en `inference2.core.sied.ar`:
`GLM-5.3-Flash-UD-IQ1_S`, `GLM-5.3-Flash-UD-IQ1_S-upstream`, `GLM-5.3-Flash-UD-Q2_K_XL`.
El RAID1 `md127` (2× WD60EFAX SMR, 5,5 TB en XFS, `/mnt/raid1hdd`) quedó con 4,8 TB libres.
El `tl-node` torrent nunca se pausó durante la operación.

## Resultado

- Copia directa octoserver → inference2 con rsync/agent-forwarding de la clave de `.30`,
  `ionice -c2 -n7 nice -n19`, `--bwlimit=60M --whole-file --partial`; sin relay ni password
  en el host.
- 8 archivos regulares + 2 symlinks, 3 carpetas; 201,82 GB lógicos enviados a 12,48 MB/s
  promedio en 4h29m (cae por el I/O de qBittorrent en la misma RAID1). Destino: 188 GiB de uso
  de disco (sparse/hardlinks).
- Verificación: listado normalizado idéntico (rutas/tamaños/symlinks, hash `5f283a87…` en
  origen y destino) y **8/8 SHA-256 de contenido iguales, diff 0**.
- No había contenedor `glm53flash` ni procesos usándolos (modelos fríos).
- Con la verificación OK se borraron las tres carpetas GLM del origen. Octoserver quedó en
  **58 % usado / 782 GB libres** (antes 68 % / 596 GB).
- El RAID1 es espejo local, no un backup remoto; replicar al NAS si hace falta.
- Evidencia: `sysadmin/dumps/2026-11-17/model-archive-glm/`, README destino
  `/mnt/raid1hdd/archive/models-archive/README-GLM.md`.

## Restauración

```bash
# desde inference2 hacia octoserver (ajustar claves/hosts)
rsync -aHAX --numeric-ids --whole-file --partial --info=progress2 \
  /mnt/raid1hdd/archive/models-archive/GLM-5.3-Flash-UD-IQ1_S \
  root@octoserver:/opt/models-archive/GLM-5.3-Flash-UD-IQ1_S
# q2_k_xl y upstream igual
```

Después se puede volver a usar `docker-compose.glm53flash.yml` (el compose monta
`/opt/models-archive`); el modelo IQ1_S es el que figura en el servicio `glm53flash`.

## Fase pendiente

Siguen calientes y sin mover: `DeepSeek-V4.1-Flash-1017-abliterated-GGUF` (Maya),
`Huihui-Qwen38-abliterated-v2-UD-Q4_K_XL` (Strata) y `/opt/strata-test`.
Pendiente para una próxima fase: el resto de `/opt/models-archive` (`UD-Q4_K_XL`,
`Qwen3.8-Flash-Next-Uncensored-Q4_K_S`, `MTP`). Los coder legacy de `/opt/llamacpp/models`
ya se movieron en la fase 3 (`docs/llamacpp-models-archive.md`).
