# Archivo frío de modelos legacy de llama.cpp en inference2

**Fecha:** 2026-11-17 (copia terminada 19:21:34 UTC).
**Alcance:** los tres modelos legacy que quedaban en `/opt/llamacpp/models`.

## Qué se movió

Origen: `/opt/llamacpp/models` en `octoserver.core.sied.ar`:

| Entrada | Tipo | Tamaño real |
|---|---|---:|
| `Llama-3.1-Pro-Coder-v1.Q4_K_M.gguf` | GGUF regular | 4,6 GB |
| `Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf` | GGUF regular | 4,4 GB |
| `qwen3.6-uncensored.gguf` | symlink roto | 58 B (target `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf` nunca existió en el host) |

Destino: `inference2:/mnt/raid1hdd/archive/llamacpp/models`, junto al README
`/mnt/raid1hdd/archive/llamacpp/README-llamacpp.md`.

## Resultado

- Copia directa octoserver → inference2 con rsync/agent-forwarding, `ionice -c2 -n7 nice -n19`,
  `--bwlimit=60M --whole-file --partial`; **no se pausaron** `tl-node-qbittorrent-1` ni
  `tl-node-autobrr-1`.
- 3 entradas (2 GGUF regulares + 1 symlink), 9,60 GB lógicos a 62,58 MB/s en 2m32s;
  destino 9 GiB de uso.
- Verificación: nombres/tamaños/target de symlink idénticos y **SHA-256 de ambos GGUF iguales**
  (`8cc4934f…` para Llama, `a7d80a35…` para Qwen2.5). El symlink roto se archivó tal cual.
- Sin servicio llama.cpp activo ni contenedor usando el árbol durante el move.
- Después de verificar se borraron los tres del origen; octoserver quedó en **58 % usado /
  789 GB libres**. `/opt/llamacpp/models` conserva sólo `.cache`.
- Evidencia: `sysadmin/dumps/2026-11-17/model-archive-llamacpp/`.
- El RAID1 es espejo local, no backup remoto.

## Restauración

```bash
rsync -aHAX --numeric-ids --whole-file --partial --info=progress2 \
  /mnt/raid1hdd/archive/llamacpp/models/ \
  root@octoserver:/opt/llamacpp/models/
```

El symlink de `qwen3.6-uncensored.gguf` sigue roto: si se quiere usar ese modelo, hay que
recuperar el GGUF original (`Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ4_XS.gguf`)
o dejarlo sólo como registro histórico.

## Fase pendiente

Ahora queda pendiente únicamente el resto de `/opt/models-archive`:
`UD-Q4_K_XL`, `Qwen3.8-Flash-Next-Uncensored-Q4_K_S` y `MTP` (y decidir si alguno queda
caliente). Se mantienen calientes Maya (`DeepSeek-V4.1-Flash-1017-abliterated-GGUF`, 498 GiB),
Strata (`Huihui-Qwen38-abliterated-v2-UD-Q4_K_XL`, 104 GiB) y `/opt/strata-test`.
