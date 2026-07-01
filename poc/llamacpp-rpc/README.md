# POC llama.cpp RPC en dos nodos

Esta prueba separa el host de modelos del host GPU usando el backend RPC de
`llama.cpp`.

## Topologia

- Nodo 1, orquestador: `172.16.1.40`, hostname objetivo `aiworker.core.sied.ar`.
- Nodo 2, GPU bridge: `172.16.1.39`, hostname objetivo `gpubridge.core.sied.ar`.
- RPC: `172.16.1.39:5000,5001,5002,5003`.
- API OpenAI-compatible: `http://172.16.1.40:8080/v1`.

El RPC de `llama.cpp` es experimental e inseguro para redes abiertas. En este
POC el script del Nodo 2 desactiva `firewalld` por decision explicita.

## Nodo 2: GPU bridge

El script corre `rpc-server` nativo por systemd y detiene Docker para liberar
recursos. Antes de apagar el stack Octofan intenta fijar los ventiladores en
PWM 26 con el CLI nativo. Luego instala `octofan-poc-safety.service`, un loop
nativo temporal que alimenta el watchdog y reaplica PWM 26 cada 30 segundos.
Tambien desactiva `firewalld` para dejar accesibles los puertos RPC.

```bash
scp -r poc/llamacpp-rpc/node2 root@172.16.1.39:/root/llamacpp-rpc-node2
ssh root@172.16.1.39 'bash /root/llamacpp-rpc-node2/setup-gpubridge.sh'
```

Verificar:

```bash
ssh root@172.16.1.39 'hostnamectl; nvidia-smi'
ssh root@172.16.1.39 'systemctl status octofan-poc-safety.service'
ssh root@172.16.1.39 'systemctl status llama-rpc@0 llama-rpc@1 llama-rpc@2 llama-rpc@3'
ssh root@172.16.1.39 "ss -ltnp | grep -E ':5000|:5001|:5002|:5003'"
ssh root@172.16.1.39 "journalctl -u 'llama-rpc@*' -f"
```

## Nodo 1: orquestador Docker

```bash
scp -r poc/llamacpp-rpc/node1 root@172.16.1.40:/root/llamacpp-rpc-node1
ssh root@172.16.1.40 'bash /root/llamacpp-rpc-node1/setup-node1.sh'
```

Copiar el GGUF a `/opt/llamacpp-rpc/models/` y editar:

```bash
ssh root@172.16.1.40 'cd /opt/llamacpp-rpc/server && vi .env'
```

Ejemplo minimo de `.env`:

```env
LLAMA_CPP_REF=master
MODELS_DIR=/opt/llamacpp-rpc/models
MODEL_PATH=/models/modelo.gguf
CTX_SIZE=8192
N_GPU_LAYERS=99
RPC_ENDPOINTS=172.16.1.39:5000,172.16.1.39:5001,172.16.1.39:5002,172.16.1.39:5003
```

Levantar:

```bash
ssh root@172.16.1.40 'cd /opt/llamacpp-rpc/server && docker compose up --build -d'
ssh root@172.16.1.40 'cd /opt/llamacpp-rpc/server && docker compose logs -f llama-server'
```

## Prueba de API

```bash
curl -sS http://172.16.1.40:8080/v1/models
curl -sS http://172.16.1.40:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "modelo",
    "messages": [{"role": "user", "content": "Responde en una frase: estas usando RPC?"}],
    "max_tokens": 64
  }'
```

## Senales de exito

En Nodo 1:

- `docker compose logs llama-server` muestra `--rpc` con los cuatro endpoints.
- La API responde en `:8080`.

En Nodo 2:

- `journalctl -u 'llama-rpc@*' -f` muestra endpoints en `0.0.0.0:5000-5003` y conexiones desde `172.16.1.40`.
- `nvidia-smi` muestra VRAM ocupada durante carga/inferencia.
- Los cuatro puertos `5000-5003` estan escuchando.

## Revertir el POC en Nodo 2

```bash
ssh root@172.16.1.39 'systemctl disable --now llama-rpc@0 llama-rpc@1 llama-rpc@2 llama-rpc@3'
ssh root@172.16.1.39 'systemctl disable --now octofan-poc-safety.service'
ssh root@172.16.1.39 'systemctl enable --now docker'
ssh root@172.16.1.39 'cd /opt/ia-octo-server && docker compose up -d'
```
