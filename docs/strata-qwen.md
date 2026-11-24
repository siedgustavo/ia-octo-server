# Strata: Huihui Qwen3.8 Flash Next abliterated V2

Stack dedicado, independiente del Compose principal. Ocupa las cuatro GPU: corre
de a uno con Maya, y los prende y apaga llama-swap (`docs/model-swap.md`). No usar
`--remove-orphans`: los stacks comparten el proyecto Compose.

## Evaluación en producción: 2026-10-30 a 2026-10-31

Objetivo: evaluar Strata durante uso cotidiano con un Qwen abliterado antes de
decidir si reemplaza a Ollama. Resultado: aprobado, quedó como servicio diario
(ver Decisión más abajo). La máquina tiene cuatro RTX 3090 de 24 GiB,
125 GiB de RAM y PCIe Gen3 x8 por GPU, sin P2P ni NVLink. Strata usa reparto
por capas, sin depender de P2P. La imagen era Strata 0.2.7 CUDA 13, motor
0.1.52 (desde 2026-11-23, 0.2.20 / 0.1.66: ver más abajo); el modelo activo es Huihui V2 UD-Q4_K_XL, no el Qwen original con que
se hizo la comparación inicial. Ollama quedó detenido, no desinstalado.

El primer arranque con el Qwen original agotó la RAM del host: el kernel mató
Strata (OOM). Se volvió a arrancar con `--resident-budget-gib 20` y límite de
contenedor de 75 GiB. Para Huihui también se reservaron 1200 MiB en la primera
GPU y 1500 MiB en las posteriores. Tras cargar se observaron aproximadamente
888–1283 MiB libres por GPU; bajo cargas largas estos márgenes pueden cambiar.
No reducir el contexto para resolver problemas de memoria sin revisar otra
configuración. El watchdog y los ventiladores automáticos seguían sanos tras
las pruebas.

### Resultados iniciales

Se comparó el **Qwen original Unsloth UD-Q4_K_XL**, mismos GGUF, contexto
configurado de 262144, temperatura 0, razonamiento desactivado y hasta 256
tokens de salida. Se usó una consigna corta de búsqueda binaria (30 tokens de
prompt) y un documento repetitivo de 6770 tokens seguido de una solicitud de
resumen. Las cifras de generación son tiempos de decode reportados por cada
motor, no incluyen carga ni prefill. Hubo tres corridas cortas y una larga por
motor; las repeticiones cortas pudieron reutilizar parte del prompt.

| Medición | Ollama | Strata | Relación aproximada |
| --- | ---: | ---: | ---: |
| Generación, prompt corto | 58–60 tok/s | 120–128 tok/s | 2,1× |
| Prefill de 6770 tokens | 848 tok/s | 1286 tok/s | 1,52× |
| Generación tras prompt largo | 56 tok/s | 96 tok/s | 1,7× |

Strata usó MTP especulativo y su caché de expertos; Ollama usó su configuración
de ese momento. Es una comparación de configuraciones reales, no una prueba de
dos motores con optimizaciones idénticas. El prompt largo de Ollama generó 210
tokens y el de Strata 256, por lo que las salidas no fueron idénticas. Son
mediciones preliminares, no una evaluación de calidad ni de contexto completo.

Con el **Huihui V2 activo**, la misma consigna corta sin razonamiento produjo
101,1 / 120,4 / 123,5 tok/s en tres corridas. Las dos últimas reutilizaron
23 de 30 tokens del prompt; la primera coincidió con otras pruebas y tardó más
en tiempo total. MTP usa la capa draft del modelo original y el target Huihui
verifica las propuestas. En esas corridas aceptó 158/220, 156/218 y 157/218
tokens propuestos. No extrapolar el resultado a contextos largos o producción
concurrida.

Se verificó una llamada de herramienta `pwd` desde OpenCode con Huihui, una
generación simple y el listado de modelos desde otra máquina sin clave. El
servicio era solo texto y un slot (visión activa desde 2026-11-24, ver más abajo).

### Uso diario validado (2026-10-30 a 2026-10-31)

Desde el 2026-10-30 14:34 el servicio quedó levantado y sano, sin reinicios ni
eventos OOM, usado a diario desde OpenCode: programación con llamadas a
herramientas y consultas de chat general. Medido sobre las primeras 24 horas
de uso real:

| Métrica | Valor observado |
| --- | --- |
| Requests procesados | 380 |
| Decode (tok/s) | min 71, mediana 101, p90 125, max 155 |
| Aciertos del caché de expertos | 99,2–99,9% |
| Errores, reinicios de contenedor, OOM | 0 |
| Cancelaciones desde OpenCode | 1, procesada sin errores |
| RAM del contenedor | 47,6 GiB estables sobre el límite de 75 GiB |
| VRAM por GPU | ~23 GiB de 24 GiB, 47–50 °C |

Hubo sesiones pesadas con contexto cerca del límite de 262144 y respondieron
bien. El host quedó sano: ~31 GiB de RAM disponibles, ventiladores en auto y
watchdog normales tras todo el período. Los tok/s de esta tabla son más bajos
que los del microbenchmark inicial porque reflejan carga real mixta (salidas
largas, caché KV grande), no una corrida óptima.

**Decisión (2026-10-31):** Strata con Huihui V2 queda como servicio de
inferencia diario en las cuatro GPU. Ollama quedó detenido como fallback (se
retiró del server el 2026-11-19). Quedan pendientes: uso concurrente real (limitado al slot
único), una evaluación formal de calidad contra otros modelos y un stress
sostenido con el contexto de 262144 completo.

## Actualización a Strata 0.2.20 (2026-11-23)

Desde el 2026-11-23 prod corre `ghcr.io/niko1221/strata:0.2.20-cuda13`, motor
0.1.66. Mismo pack, GGUF, MTP y argumentos que con 0.2.7; solo cambian el
`exe` del engine y dos variables de entorno.

**Workaround obligatorio:** `STRATA_HC_Q8_TC=0` y `STRATA_HC_Q8_BF16TC=0` en el
`env` de `strata/strata-qwen.json`. Sin ellas el engine 0.1.66 carga, pero la
primera request falla con `verify: layer 0 never rang (operation not supported
on global/shared address space)` y el server reinicia el engine en bucle. Es el
bug upstream #6713 (kernels Tensor Core de hyper-connection Q8_0 que leen
memoria compartida con `__ldg`; afecta archivos Unsloth `UD-*` en RTX 30/40),
con fix #6714 anunciado para 0.2.21. Hacen falta las dos: con una sola sigue
fallando. Al pasar a 0.2.21, probar sin ellas.

A/B con `scripts/bench-openai-timings.py` (temperatura 0, sin razonamiento,
nonce, `cache_n = 0`), mismos prompts (snapshot de `docs/*.md`), mismo día, 4
GPU a 250 W, MTP `--spec 4` en ambos:

| Caso | Decode 0.2.7 | Decode 0.2.20 | Prefill 0.2.7 | Prefill 0.2.20 |
| --- | ---: | ---: | ---: | ---: |
| Corto (~64 tok, 256 de salida) | 104 / 141 / 147 | 147 / 163 / 164 | — | — |
| Código (~97 tok, 1024 de salida) | 131 / 141 | 161 / 165 | — | — |
| 8,7k de prompt | 99,9 | 120,5 | 873 | 1786 |
| 37k de prompt | 94,7 | 118,9 | 1249 | 3564 |
| 114k de prompt | 97,6 | 115,4 | 1404 | 4732 |

Tiempo total de la request de 114k + 512 de salida: 86,6 s → 28,7 s. Aceptación
de MTP igual (53–62 % en largos, ~85 % en corto). Tool calling verificado
(`tool_calls` con argumentos correctos). En carga: ~26–29 GiB de RAM del
contenedor (antes ~47), GPU 19,4–22,5 GiB.

Límite de potencia (mismo día, misma instancia): sin el tope de 250 W (de fábrica
350/350/370/350 W) el decode queda igual (115–167 tok/s en ambos) y el prefill
largo gana solo 3–6 % (114k: 4680 → 4890 tok/s, 28,9 → 27,9 s). Los picos fueron
298–326 W sin tope contra 242–250 W con tope. No compensa el riesgo de caída de
bus que motivó el límite: queda en 250 W.

DFlash2 en vez de MTP (mismo día, 250 W): drafter tuneado de Strata
`qwen3.8-flash-next-dflash2.strata1.q4_0-selq4.pack` (release v0.2.16, SHA-256
`4df2e5ab…664c`), `--draft dflash2 --draft-fallback none --spec 6 --draft-conf
0.35`. Para que el server lo use con Huihui hay que pasar el pack en
`"user_args": ["--draft-model", …]` y `"drafting": "dflash2"`; si no, como el
nombre del modelo no es un set Unsloth conocido, dice "the DFlash2 drafter isn't
downloaded yet" y arranca con MTP. Dos corridas de los casos largos:

| Caso | Decode MTP | Decode DFlash2 | Prefill MTP | Prefill DFlash2 |
| --- | ---: | ---: | ---: | ---: |
| Corto | 162 / 162 / 162 | 171 / 171 / 188 | 170 | 149–162 |
| Código | 164 / 168 | 167 / 176 | 199–207 | 194–201 |
| 8,7k | 120,5 / 122,5 | 110,1 / 115,5 | 1786–1792 | 1925–1937 |
| 37k | 114,9 / 118,9 | 106,6 / 111,1 | 3552–3564 | 3782–3952 |
| 114k | 115,4 / 116,7 | 115,3 / 107,2 | 4680–4732 | 4943–5180 |

DFlash2 gana 5–15 % de decode en contexto corto y 5–10 % de prefill (no carga la
capa MTP, más VRAM para expertos), pero pierde 5–8 % de decode con prompts
largos: acepta ~50 % de lo propuesto contra 53–62 % de MTP. Strata mismo marca
DFlash2 como `slower` en sm_86. Como el uso real (OpenCode) es de contexto
largo, **se queda MTP**, fijado con `"drafting": "mtp"` en
`strata/strata-qwen.json` para que el modo `auto` no cambie solo. El pack queda
en `/opt/strata-test-df2` para futuras pruebas.

## Visión (desde 2026-11-24)

Strata acepta imágenes (`image_url` de OpenAI, bloques `image` de Anthropic) con el lector
`strata-vision` del engine y el proyector de Unsloth para Qwen3.8-Flash-Next
(`/opt/models-archive/UD-Q4_K_XL/mmproj-F16.gguf`, 904 MB). Huihui no publica un proyector
propio; la abliteración no toca la torre visual y el de Unsloth funciona.

- Config: sección `"vision"` en `strata/strata-qwen.json` (`exe`, `mmproj`, `model`,
  `"gpu": true`). El server agrega `--vision` solo; como ya hay `--vram-reserve-mib 1200` no
  suma reserva extra. El compose monta el proyector en `/models-vision` (`STRATA_MMPROJ`).
- `/v1/models` declara `input_modalities: ["text", "image"]` y el log dice `images on`.
- El lector corre en la GPU 0 (la que tiene las primeras capas): ~1,3 GB más, quedan
  ~3,4 GB libres.
- Prueba: imagen sintética (cuadrado rojo, círculo azul, texto `OCTO 4729`) descrita
  correctamente, directo en `:18080` y por llama-swap `:18100`, ~2 s.
- Rendimiento con la batería de siempre: sin cambios (decode 114–166 tok/s; prefill
  1788 / 3531 / 4787 tok/s en 8,7k / 37k / 114k).
- OpenCode: el modelo `strata/huihui-…` declara `"input": ["text", "image"]` en
  `~/.config/opencode/opencode.json` (config local, no está en el repo).

Rollback: volver `docker-compose.strata-qwen.yml` y `strata/strata-qwen.json` al
commit anterior (imagen 0.2.7, engine 0.1.52) y reiniciar `llama-swap`.

## Modelo y preparación

Se usa `huihui-ai/Huihui-Qwen3.8-Flash-Next-abliterated-v2-GGUF`, carpeta
`unsloth-UD-Q4_K_XL-V2`, revisión `411f1f7349c9711e6f75aa8d20e1612eb3a4d55d`.
Los cuatro GGUF van en `/opt/models-archive/Huihui-Qwen38-abliterated-v2-UD-Q4_K_XL`.
Verificar SHA-256 contra la revisión publicada en Hugging Face antes de crear
el pack. No desactivar la verificación general de Strata ni reutilizar el pack
de otro modelo: contiene los pesos densos y el tokenizer propios.

SHA-256 publicados para los shards de esa revisión, verificados al descargar:

| Shard | SHA-256 |
| --- | --- |
| 00001 | `4448186216b3af4cc558bbce2c3213f01608f8f8b2e5267a9767971dd3ec8082` |
| 00002 | `ab283aba22daee321944dad65b09180810140fc75502c0791200cf01b85f9c75` |
| 00003 | `2a8d2e69ba47fef6b42c953c07a24b5d4c59c1c2cdc89b2bc17e13e000a62fa0` |
| 00004 | `0d626450754c554235f93653b8f7c874c7c2d35380b9efab5b0852d616b84702` |

Fuente: [repositorio del modelo](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-Flash-Next-abliterated-v2-GGUF).

Con la imagen fijada en el Compose, crear el pack una vez:

```sh
docker run --rm --memory 12g \
  --entrypoint /opt/strata/terminal/python/bin/python \
  -v /opt/models-archive/Huihui-Qwen38-abliterated-v2-UD-Q4_K_XL:/models:ro \
  -v /opt/strata-test:/data -w /opt/strata/terminal \
  ghcr.io/niko1221/strata:0.2.20-cuda13@sha256:ca61966471c97478f02a519386bdae1636c853705baffc413a6a4d92f82718d7 \
  tools/iq_pack.py --gguf /models/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf \
  --out /data/Strata-data/packs/huihui-v2-ud-q4_k_xl --compat-bf16
```

La capa MTP original debe existir en `/opt/strata-test/Strata-data/mtp/rt`.
La usa el modelo como borrador; las propuestas son verificadas por Huihui.
El servicio no requiere clave; limitar el acceso a una red de confianza.

## Operación

```sh
docker compose -f docker-compose.strata-qwen.yml up -d
docker compose -f docker-compose.strata-qwen.yml logs -f
docker compose -f docker-compose.strata-qwen.yml stop
```

Escucha por defecto en todas las interfaces del host, puerto `18080` (se puede
restringir con `STRATA_BIND`). API OpenAI compatible en `/v1`, sin autenticación.
HTTP no cifra las solicitudes: usar solo una red de
confianza, o un túnel SSH/TLS fuera de ella. No implementa la API
nativa de Ollama (`/api/*`). Acepta imágenes desde 2026-11-24 (ver "Visión"). Se permiten el
nombre `octoserver.core.sied.ar` y la IP `172.16.1.6` en `allowed_hosts`;
actualizarlos si cambia la dirección del host. Se reserva el contexto nativo de
262144 tokens, con un solo slot, MTP, presupuesto de 20 GiB
para expertos en RAM y límite de contenedor de 75 GiB para proteger al host.
El límite y las reservas de VRAM son conservadores, no una garantía de que un
contexto completo bajo carga real no pueda agotar memoria.

Desde 2026-10-31 este stack es el servicio diario. Desde 2026-11-19 lo maneja
llama-swap: queda precargado tras un reboot y se apaga cuando OpenCode pide Maya.
No usar `compose up -d` / `stop` a mano (ver `docs/model-swap.md`). Ollama se
retiró el 2026-11-19 (`ollama-custom/README.md`).
Comprobar watchdog, ventiladores en automático, temperatura y memoria tras
cualquier cambio de servicio.

### Convivencia con el Compose principal

- `docker compose ls` muestra un único proyecto `ia-octo-server` con
  `docker-compose.yml` y `docker-compose.strata-qwen.yml`. Por eso
  `--remove-orphans` desde el Compose principal **elimina `strata-qwen`**
  (ya pasó con `qwen38flash` el 2026-10-04). Nunca usarlo con Strata arriba.
- Para desplegar monitoreo/controller usar siempre la lista de servicios:
  `docker compose up --build -d octofan-controller prometheus node-exporter grafana`.
- `ollama.enabled: false` (repo y prod): el servicio ya no existe.
- `watchdog.gpu_recovery_restart_containers` y `ai_recovery_restart_containers`
  listan `strata-qwen` y `maya-deepseek`; el controller solo reinicia los que están
  corriendo, así que nunca prende el backend parado encima del activo.
- Desde 2026-10-31 el controller monitorea Strata: `strata.enabled: true` hace que
  sondee `/v1/models` de cada entrada de `strata.endpoints` (Strata `:18080` y Maya
  `:18090`; está arriba si responde cualquiera) y lo refleje en `/api/status`,
  el OLED (`Strata 1/1 loaded` / `Strata DOWN`), los LEDs y Prometheus
  (`octofan_ai_up{source="strata"}`, `octofan_ai_running_models`). Además el
  watchdog de IA (`watchdog.ai_recovery_*`) reinicia el contenedor que esté corriendo tras tres ciclos
  seguidos de health check fallando, con cooldown de 900 s y sin reiniciar mientras
  Docker reporta el contenedor `starting` (ventana de carga del modelo). AI recovery
  nunca corta el alimento del firmware: el reset de placa queda solo para el host.

Comprobaciones desde la red de confianza:

```sh
curl -fsS http://octoserver.core.sied.ar:18080/v1/models
curl -fsS http://octoserver.core.sied.ar:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"huihui-qwen3.8-flash-next-abliterated-v2-ud-q4_k_xl","messages":[{"role":"user","content":"Responde OK"}],"max_tokens":64}'
```

En el OpenCode configurado para esta prueba, elegir en `/models` el modelo
`strata/huihui-qwen3.8-flash-next-abliterated-v2-ud-q4_k_xl`. Ese proveedor
es configuración local de OpenCode y no se distribuye automáticamente con este
repositorio. El controller consulta la API OpenAI-compatible de Strata
(`/v1/models`) para salud; no emula los endpoints nativos de Ollama.
