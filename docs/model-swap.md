# Cambio de modelo Strata <-> Maya (llama-swap)

Strata (Qwen3.8 Flash Next, `:18080`) y Maya (DeepSeek-V4.1-Flash, `:18090`) ocupan las 4 GPU: corre uno
solo. Desde 2026-11-19 los prende y apaga **llama-swap** segun el modelo que se pida.

## Como funciona

- `llama-swap` (v272, binario en `/opt/llama-swap/`, unidad `llama-swap.service`) escucha en
  `http://octoserver.core.sied.ar:18100/v1` y es OpenAI-compatible. Config: `llama-swap/config.yaml`.
- Un pedido con `model` = `huihui-qwen3.8-flash-next-abliterated-v2-ud-q4_k_xl` o
  `deepseek-v4.1-flash-abliterated` arranca ese backend y apaga el otro. El pedido espera la carga.
- Cada `cmd` hace primero `docker stop` del otro container, por si alguno se levanto por fuera.
- Un pedido en curso termina antes del cambio. Medido: un pedido de 1500 tokens a Strata termino completo
  y recien despues se apago Strata.
- Al arrancar el host queda **Maya** (`hooks.on_startup.preload`).
- Los dos stacks tienen `restart: "no"`: Docker no levanta ninguno solo.

| Cambio | Tiempo hasta la primera respuesta (medido 2026-11-19) |
|---|---|
| -> Maya | 60-75 s |
| -> Strata | 140-150 s |

## Quien cambia

- **Solo OpenCode** (providers `strata` y `maya` apuntan a `:18100`). Elegir el modelo en OpenCode y
  mandar un mensaje: el primero tarda lo de la tabla.
- Jaime, sied-poster y el chat (Open WebUI) siguen yendo a `:18080` / `:18090` directo, con su cadena de
  respaldo (Strata -> Maya -> qwen3.8:27b de inference2). Usan el que este prendido y **nunca provocan un
  cambio**.

## Controller

- `strata.endpoints` lista los dos (`Strata` `:18080`, `Maya` `:18090`): el estado es `up` si responde
  cualquiera. La OLED muestra cual (`Maya 1/1 loaded`).
- La recuperacion de IA y de GPU (`*_restart_containers: [strata-qwen, maya-deepseek]`) reinicia solo los
  containers que **estan corriendo**: nunca prende el que se apago a proposito.
- Si un backend se cae del todo (container parado), el controller no lo levanta: lo levanta llama-swap
  con el proximo pedido de OpenCode. Mientras tanto los servicios caen a qwen3.8:27b.

## Operacion

```bash
curl -s http://octoserver.core.sied.ar:18100/running          # que modelo esta arriba
# forzar un modelo sin OpenCode:
curl -s http://octoserver.core.sied.ar:18100/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"huihui-qwen3.8-flash-next-abliterated-v2-ud-q4_k_xl","messages":[{"role":"user","content":"hola"}],"max_tokens":8}'
curl -s -X POST http://octoserver.core.sied.ar:18100/api/models/unload   # apagar todo (libera las GPU)
journalctl -u llama-swap -f
```

- **No** usar `docker compose ... up -d` / `stop` de Strata o Maya a mano: llama-swap no se entera. Si
  pasa igual, el proximo cambio lo corrige (cada `cmd` para el otro).
- Si se cuelga: `systemctl restart llama-swap` (vuelve a precargar Maya).
- Instalar en otro host: copiar el binario de la release v272 a `/opt/llama-swap/`,
  `cp llama-swap/llama-swap.service /etc/systemd/system/`, `systemctl enable --now llama-swap`.
- Validar la config: `/opt/llama-swap/llama-swap -validate -config llama-swap/config.yaml`.
