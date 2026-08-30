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
    normal), recorre los `SLOT_COUNT` slots configurados y hace
    `POST /slots/{n}?action=save` por cada uno antes de dejar morir al
    proceso, guardando el KV de cada slot en
    `$SLOT_SAVE_PATH/$KV_CACHE_FILE.slot{n}.bin`.
  - Al arrancar, por cada slot cuyo archivo ya exista, espera a que
    `/health` responda y hace `POST /slots/{n}?action=restore` antes de que
    llegue trafico real.
  - `SLOT_COUNT` debe coincidir siempre con el `--parallel` del compose; si
    no coinciden, algun slot queda sin persistir o el restore falla.
- Cada compose (`docker-compose.qwen38flash.yml`, `docker-compose.glm53flash.yml`):
  - Agrega `--slot-save-path /kv-cache` al comando de `llama-server`.
  - Monta un volumen de host propio por servicio (`./kv-cache` para qwen,
    `./kv-cache-glm` para GLM, configurables via `QWEN_KV_CACHE_DIR` /
    `GLM_KV_CACHE_DIR`) en `/kv-cache`.
  - Define `SLOT_SAVE_PATH=/kv-cache`, `KV_CACHE_FILE` (nombre por modelo,
    ej. `qwen3.8-flash-next`, sin extension) y `SLOT_COUNT` como variables
    de entorno leidas por el entrypoint.
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
- El archivo de cache (`kv-cache/qwen3.8-flash-next.slot0.bin`,
  `kv-cache-glm/glm-5.3-flash-iq1-s.slot0.bin`) se sobreescribe en cada
  `save`; no hay historial ni versionado por sesion (ambos servicios corren
  con `--parallel 1`, un unico slot).
- Un primer arranque sin archivo previo se comporta igual que antes de este
  cambio (sin restore).
- El formato del archivo de save/restore de llama.cpp codifica `--parallel`
  (`n_stream`). Si se cambia `--parallel` entre un `save` y el siguiente
  `restore`, falla con `n_stream mismatch` (probado, ver mas abajo). El
  entrypoint lo maneja sin crashear (loguea el error y sigue arrancando),
  pero el archivo viejo queda inutil: borrarlo despues de cualquier cambio
  de `--parallel`.

## Investigacion: ¿se puede "flapear" entre conversaciones sin perder cache?

El save/restore a disco resuelve sobrevivir un *reinicio*. Pregunta distinta:
¿se puede, con el proceso vivo, saltar entre varios proyectos/conversaciones
de OpenCode sin perder el prefill de cada uno? Investigado el 2026-08-30
sobre `qwen38flash`.

**Lo que existe en llama.cpp:** `--cache-ram N` (mueve prompts completos a
RAM del host como "slots extra") + `--cache-idle-slots` (activado por
default si `cache-ram != 0`). El PR que lo introdujo
([#16391](https://github.com/ggml-org/llama.cpp/pull/16391)) lo describe
como "the host-memory prompt cache acts as 'extra slots' [...] we can now
use a single server slot without trashing the prompt cache" — en teoria,
exactamente lo que buscabamos.

**Prueba 1 (con `--parallel 1`, `--cache-ram 65536`, `--checkpoint-min-step
1024`):** se corrieron dos sesiones reales de OpenCode sobre temas distintos
(A: `docker-compose.yml`, B: `controller/octofan_controller`) y se volvio a
A. Resultado: `f_sim_best=0.854`, tuvo que reprocesar **2030 de 13272
tokens** — no hubo restore desde RAM. Comparando 0.854 con la proporcion del
system prompt compartido entre A y B (~11184/13130 ≈ 0.852), quedo claro que
el match fue contra el estado de B que seguia activo en VRAM (reuso normal
de prefijo), no contra una entrada de A rescatada de `--cache-ram`.

**Causa exacta (leida en el codigo fuente real de la build, commit
`6c84c7d5d8` de `ggml-org/llama.cpp`, `tools/server/server-context.cpp`):**

- `cache_idle_slots` (linea ~2388) guarda a RAM los slots que **no** estan
  manejando la tarea nueva, iterando `for slot : slots if !is_processing()`.
  Con `--parallel 1` hay un unico slot, y ese slot pasa a estar "processing"
  apenas arranca la tarea nueva — el loop nunca encuentra "otro slot idle"
  para guardar. **Es un no-op estructural con un solo slot**, sea cual sea
  el valor de `--cache-ram`.
- El unico camino que si puede disparar un guardado a RAM con un solo slot
  esta en `get_available_slot` (linea ~1573): antes de reusar el slot unico
  para una request distinta, calcula `f_keep` (fraccion del contenido actual
  que se conserva) y **solo cachea a RAM si `f_keep < 0.5`** — o sea, solo si
  el cambio de conversacion haria perder mas de la mitad del contexto
  actual. Con el system prompt+tools de OpenCode dominando el conteo de
  tokens de cualquier sesion corta, `f_keep` casi nunca baja de 0.5, asi que
  esta ruta casi no se activa en el uso real.

**Prueba 2: `--parallel 2`** (para tener 2 slots reales, cada uno con
131072 tokens de contexto en vez de 262144). Arranco sano, sin OOM
(`n_slots = 2, n_ctx_slot = 131072`, VRAM libre similar a antes). Se repitio
el mismo flujo A/B/A. Resultado real observado en los logs:

- El slot 1 quedo ocupado por las llamadas del **sub-agente "title"** interno
  de OpenCode (genera el titulo de la sesion con un system prompt mucho mas
  chico) — no por la sesion B.
- Las llamadas del agente **"build"** de A y B (las que importan) siguieron
  cayendo **las dos en el slot 0**: `get_available_slot` elige el slot de
  **mejor similitud de prefijo**, no "un slot libre para una conversacion
  nueva". Como A y B comparten el mismo system prompt gigante, B siempre
  matcheo mejor contra el slot ya ocupado (por A) que contra el slot vacio,
  y lo piso igual que con un solo slot (`f_keep=0.864`, descarto ~1675
  tokens de A).

**Conclusion:** ni `--cache-ram` ni sumar slots con `--parallel` resuelven
"tener N conversaciones de OpenCode residentes, cada una en lo suyo" sin
forzar `id_slot` explicitamente por proyecto (algo que OpenCode no expone
hoy via su cliente OpenAI-compatible) — el ruteo automatico de llama.cpp fue
disenado para *multi-tenancy generico* (elegir el slot mas parecido a la
request entrante), no para aislar proyectos por identidad. Se revirtio
`--parallel` a `1` (para no perder la mitad del contexto nativo sin
beneficio real) y se dejo `--cache-ram 65536`/`--checkpoint-min-step 1024`
puestos igual: no demostraron beneficio en el caso de uso real de OpenCode,
pero tampoco costo medible, y cubren el caso puntual de saltar a una
conversacion lo bastante distinta como para cruzar el umbral `f_keep < 0.5`.

Para lograr el aislamiento real por proyecto haria falta un proxy delante de
llama.cpp que asigne `id_slot` de forma deterministica segun el proyecto
(ej. hash del `cwd`/session id de OpenCode) — no investigado en profundidad,
queda pendiente si se vuelve a necesitar.
