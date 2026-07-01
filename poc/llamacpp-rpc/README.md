# POC llama.cpp RPC en dos nodos

Esta prueba separa el host de modelos del host GPU usando el backend RPC de
`llama.cpp`.

## Topologia

- Cliente RPC / host de modelos: `aiworker.core.sied.ar` (`172.16.1.40`).
- Servidor RPC / Octofan GPU bridge: `octoserver.core.sied.ar` (`172.16.1.39`).
- RPC: `octoserver.core.sied.ar:5000,5001,5002,5003`.
- APIs OpenAI-compatible: `http://aiworker.core.sied.ar:8080/v1` a `:8083/v1`.

El RPC de `llama.cpp` es experimental e inseguro para redes abiertas. Usarlo
solo en LAN privada o detras de VPN/firewall.

## octoserver: RPC bridge

`octoserver` corre el stack Octofan normal y cuatro containers RPC, uno por
GPU. No carga modelos GGUF y no corre `llama-server`.

```bash
ssh root@octoserver.core.sied.ar 'cd /opt/ia-octo-server && ./poc/llamacpp-rpc/node2/setup-octoserver.sh'
```

Verificar:

```bash
ssh root@octoserver.core.sied.ar 'cd /opt/ia-octo-server && docker compose ps'
nc -vz octoserver.core.sied.ar 5000
nc -vz octoserver.core.sied.ar 5001
nc -vz octoserver.core.sied.ar 5002
nc -vz octoserver.core.sied.ar 5003
```

## aiworker: cliente RPC y modelos

`aiworker` corre los `llama-server` en Docker. Los modelos GGUF viven en
`/opt/llamacpp-rpc/models` dentro de `aiworker`.

```bash
scp -r poc/llamacpp-rpc/node1 root@aiworker.core.sied.ar:/root/llamacpp-rpc-node1
ssh root@aiworker.core.sied.ar 'bash /root/llamacpp-rpc-node1/setup-node1.sh'
ssh root@aiworker.core.sied.ar 'cd /opt/llamacpp-rpc/server && docker compose pull && docker compose up -d'
```

Mapeo por defecto:

```text
qwen3coder           -> octoserver.core.sied.ar:5000 -> GPU 0 -> API :8080
qwen3.6-uncensored   -> octoserver.core.sied.ar:5001 -> GPU 1 -> API :8081
llama3.1-pro         -> octoserver.core.sied.ar:5002 -> GPU 2 -> API :8082
playground           -> octoserver.core.sied.ar:5003 -> GPU 3 -> API :8083
```

## Validacion

En `octoserver`, el controller solo monitorea puertos RPC:

```bash
curl -fsS http://octoserver.core.sied.ar:8000/api/status | python3 -m json.tool
curl -fsS http://octoserver.core.sied.ar:8000/metrics | grep octofan_rpc
```

En `aiworker`, probar la API de modelos:

```bash
curl -fsS http://aiworker.core.sied.ar:8080/v1/models
curl -fsS http://aiworker.core.sied.ar:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3coder","messages":[{"role":"user","content":"Responde OK"}],"max_tokens":8}'
```
