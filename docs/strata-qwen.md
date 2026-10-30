# Strata: Huihui Qwen3.8 Flash Next abliterated V2

Stack dedicado, independiente del Compose principal. Mantener Ollama y otros
servidores de modelos detenidos mientras Strata ocupa las cuatro GPU. No usar
`--remove-orphans`: los stacks comparten el proyecto Compose.

## Modelo y preparación

Se usa `huihui-ai/Huihui-Qwen3.8-Flash-Next-abliterated-v2-GGUF`, carpeta
`unsloth-UD-Q4_K_XL-V2`, revisión `411f1f7349c9711e6f75aa8d20e1612eb3a4d55d`.
Los cuatro GGUF van en `/opt/models-archive/Huihui-Qwen38-abliterated-v2-UD-Q4_K_XL`.
Verificar SHA-256 contra la revisión publicada en Hugging Face antes de crear
el pack. No desactivar la verificación general de Strata ni reutilizar el pack
de otro modelo: contiene los pesos densos y el tokenizer propios.

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
La clave va en `/opt/strata-test/api-key`, propiedad de root, modo `0600`;
generarla con `openssl rand -hex 24` si no existe y distribuirla por un canal
seguro. No guardarla en Git.

## Operación

```sh
docker compose -f docker-compose.strata-qwen.yml up -d
docker compose -f docker-compose.strata-qwen.yml logs -f
docker compose -f docker-compose.strata-qwen.yml stop
```

Escucha en `127.0.0.1:18080`; usar un túnel SSH para clientes remotos. API
OpenAI compatible en `/v1`, autenticada con bearer token. No implementa la API
nativa de Ollama. Solo texto; la visión no está configurada. Se reserva el
contexto nativo de 262144 tokens, con un solo slot, MTP, presupuesto de 20 GiB
para expertos en RAM y límite de contenedor de 75 GiB para proteger al host.
El límite y las reservas de VRAM son conservadores, no una garantía de que un
contexto completo bajo carga real no pueda agotar memoria.

Ollama permanece instalado y puede restaurarse después de detener Strata con
`docker start octofan-ollama`. No iniciar ambos modelos en las mismas GPU.
Comprobar watchdog, ventiladores en automático, temperatura y memoria tras
cualquier cambio de servicio.
