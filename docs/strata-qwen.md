# Strata: Huihui Qwen3.8 Flash Next abliterated V2

Stack dedicado, independiente del Compose principal. Mantener Ollama y otros
servidores de modelos detenidos mientras Strata ocupa las cuatro GPU. No usar
`--remove-orphans`: los stacks comparten el proyecto Compose.

## Prueba en curso: 2026-10-30

Objetivo: evaluar Strata durante uso cotidiano con un Qwen abliterado antes de
decidir si reemplaza a Ollama. La máquina tiene cuatro RTX 3090 de 24 GiB,
125 GiB de RAM y PCIe Gen3 x8 por GPU, sin P2P ni NVLink. Strata usa reparto
por capas, sin depender de P2P. La imagen es Strata 0.2.7 CUDA 13, motor
0.1.52; el modelo activo es Huihui V2 UD-Q4_K_XL, no el Qwen original con que
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
servicio es solo texto y un slot. Aún faltan pruebas sostenidas de programación,
herramientas, cancelaciones, estabilidad, uso concurrente y contextos largos
(incluido el límite de 262144), además de evaluar calidad y consumo real.

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
  ghcr.io/niko1221/strata:0.2.7-cuda13@sha256:db96cd9b111c930f7deb77444f38f66e53db43af57644a33a9e8a2f05f038360 \
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
nativa de Ollama. Solo texto; la visión no está configurada. Se permiten el
nombre `octoserver.core.sied.ar` y la IP `172.16.1.6` en `allowed_hosts`;
actualizarlos si cambia la dirección del host. Se reserva el contexto nativo de
262144 tokens, con un solo slot, MTP, presupuesto de 20 GiB
para expertos en RAM y límite de contenedor de 75 GiB para proteger al host.
El límite y las reservas de VRAM son conservadores, no una garantía de que un
contexto completo bajo carga real no pueda agotar memoria.

Ollama permanece instalado y puede restaurarse después de detener Strata con
`docker start octofan-ollama`. No iniciar ambos modelos en las mismas GPU.
Comprobar watchdog, ventiladores en automático, temperatura y memoria tras
cualquier cambio de servicio.

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
repositorio. El controller sigue configurado para consultar Ollama; la API de
Strata no reemplaza transparentemente los endpoints nativos de Ollama ni su
telemetría en el controller.
