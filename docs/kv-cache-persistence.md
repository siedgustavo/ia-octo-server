# Cache de KV persistente a disco (qwen38flash y glm53flash)

Mecanismo para que un reinicio del contenedor de `llama-server` no obligue a
volver a prefillear desde cero el contexto largo de una sesion de OpenCode.
Usa los endpoints nativos de llama.cpp `POST /slots/{id}?action=save` y
`action=restore`, envueltos en un entrypoint que se dispara automaticamente
al apagar y arrancar el contenedor.

## Motivacion

Con `--parallel 1` cada servicio (`qwen38flash`, `glm53flash`) corre un unico
slot. Mientras el proceso de `llama-server` sigue vivo, el prefill de una
sesion de OpenCode que crece turno a turno ya se reutiliza automaticamente
via `cache_prompt` (comparacion de prefijo comun / LCP). Ese cache vive solo
en la memoria GPU del proceso: un `docker restart`, un `docker compose up`
tras un cambio de imagen, o un crash, lo pierden por completo y la proxima
solicitud de OpenCode reprocesa todo el contexto acumulado desde el token 0.

Para una sesion larga (10-15k tokens de contexto, cosa comun en OpenCode una
vez que leyo varios archivos) eso significa decenas de segundos de prefill
perdidos en cada reinicio.

## Implementacion

- `llamacpp/entrypoint-kv-cache.sh`: entrypoint generico (lo usan tanto
  `llamacpp/Dockerfile` como `llamacpp/Dockerfile.qwen38flash`) que envuelve
  `llama-server`:
  - Al recibir `SIGTERM`/`SIGINT` (un `docker stop`/`docker compose down`
    normal), hace `POST /slots/0?action=save` antes de dejar morir al
    proceso, guardando el KV del slot 0 en `$SLOT_SAVE_PATH/$KV_CACHE_FILE`.
  - Al arrancar, si ese archivo ya existe, espera a que `/health` responda y
    hace `POST /slots/0?action=restore` antes de que llegue trafico real.
- Cada compose (`docker-compose.qwen38flash.yml`, `docker-compose.glm53flash.yml`):
  - Agrega `--slot-save-path /kv-cache` al comando de `llama-server`.
  - Monta un volumen de host propio por servicio (`./kv-cache` para qwen,
    `./kv-cache-glm` para GLM, configurables via `QWEN_KV_CACHE_DIR` /
    `GLM_KV_CACHE_DIR`) en `/kv-cache`.
  - Define `SLOT_SAVE_PATH=/kv-cache` y `KV_CACHE_FILE=opencode.bin` como
    variables de entorno leidas por el entrypoint.
  - Sube `stop_grace_period` a `120s` para darle tiempo al save de terminar
    con contextos largos antes de que Docker mande `SIGKILL`.

**Atado a la configuracion exacta con la que se guardo.** El archivo de cache
es un volcado binario del estado interno de llama.cpp: build de llama.cpp,
modelo/GGUF, cuantizacion de KV (`--cache-type-k`/`-v`), split de tensores y
contexto deben ser los mismos al restaurar. Si se cambia cualquiera de esos
parametros, borrar el archivo antes de reiniciar (el restore puede fallar o,
peor, devolver un estado inconsistente sin fallar ruidosamente).

**Limitacion no obvia:** si la request de restore/segundo turno es
*exactamente* el mismo prompt ya guardado (sin nada nuevo agregado al final),
llama-server lo reprocesa completo en vez de detectarlo como ya cacheado. No
afecta el caso real de OpenCode (la conversacion siempre crece agregando
turnos nuevos al final), pero conviene saberlo si se arma un test sintetico.

## Pruebas realizadas (2026-08-30, octoserver.core.sied.ar)

Metodologia: se corrio una sesion real de OpenCode (`opencode run`, no un
curl sintetico) contra el modelo dedicado, se dejo crecer el contexto
leyendo archivos del repo, se reinicio el contenedor a mitad de sesion
(`docker stop` + `docker start`), y se continuo la misma sesion
(`opencode run -s <session-id> "..."`) para confirmar que el turno siguiente
reusa el cache restaurado.

### qwen38flash (Qwen3.8-Flash-Next, ctx 262144, layer split 4x RTX 3090)

Config de referencia: ver `docs/qwen38flash-split-benchmark.md` (layer split,
~559 tok/s de prompt processing en frio).

1. Turno 1 (sesion nueva): OpenCode lee 3 archivos del repo, el slot llega a
   **14723 tokens** de contexto.
2. `docker stop qwen38flash` (~1.9s) -> el entrypoint guarda el slot:
   `n_saved=14723`, `save_ms` de milisegundos, sin reprocesar nada.
3. `docker start qwen38flash` (~0.3s + tiempo de carga del modelo en las 4
   GPUs) -> el entrypoint restaura: `n_restored=14723`, `restore_ms=664`.
4. Turno 2 (misma sesion, mensaje nuevo): OpenCode responde correctamente
   (`docker-compose.qwen38flash.yml:26`). El servidor reporta
   `f_keep=1.000` y solo prefillea **39 tokens nuevos** en **1.2s**, en vez
   de reprocesar los 14723 completos (que a ~550 tok/s hubiera tomado unos
   ~27s). El turno completo (prefill + generacion) tardo **6.4s**.

### glm53flash (GLM-5.3-Flash UD-IQ1_S, ctx 131072, auto-fit 4x RTX 3090)

Config de referencia: ver `docs/glm53flash-benchmark.md` (auto-fit,
reasoning_effort max, ~15 tok/s de generacion por el cuello de botella del
MoE en CPU/RAM).

1. Turno 1 (sesion nueva): OpenCode lee 3 archivos del repo, el slot llega a
   **15060 tokens** de contexto (sesion completa tardo ~5:16 por el
   reasoning_effort max de GLM).
2. `docker stop glm53flash` (~2.6s) -> guarda `n_saved=15060` en un archivo
   de ~389 MiB.
3. `docker start glm53flash` -> restaura `n_restored=15060`,
   `restore_ms=669`.
4. Turno 2 (misma sesion): OpenCode responde correctamente (linea 44 de
   `docker-compose.glm53flash.yml`). `f_keep=1.000`, solo **23 tokens
   nuevos** de prefill (**1.2s**). El resto del tiempo del turno (8.7s
   total) es generacion a los ~15 tok/s esperados para este modelo, no
   prefill.

### Conclusion

El mecanismo funciona igual en ambos servicios dedicados: un reinicio del
contenedor deja de costar un re-prefill completo del contexto de OpenCode.
El costo pasa a ser el restore desde disco (bajo 1 segundo en ambos casos
probados) mas el prefill incremental de lo que se agrego despues del ultimo
save.

## Consideraciones operativas

- **VRAM compartida:** `qwen38flash` y `glm53flash` no entran juntos en las
  4 RTX 3090 (cada uno ocupa practicamente toda la VRAM disponible). Antes
  de levantar uno hay que bajar el otro:
  ```bash
  docker compose -f docker-compose.qwen38flash.yml stop qwen38flash
  docker compose -f docker-compose.glm53flash.yml up -d
  ```
- El archivo de cache (`kv-cache/opencode.bin`, `kv-cache-glm/opencode.bin`)
  se sobreescribe en cada `save`; no hay historial ni versionado por sesion
  (ambos servicios corren con `--parallel 1`, un unico slot).
- Un primer arranque sin archivo previo se comporta igual que antes de este
  cambio (sin restore).
