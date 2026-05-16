# Operations

## Start With Hardware

```bash
docker compose up --build -d
```

Open:

- Controller: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Ollama: `http://localhost:11434`

Grafana login is `admin` / `octofan`.

## Start Without Hardware

Use mock mode to validate the stack on any machine:

```bash
OCTOFAN_MOCK=1 docker compose up --build -d
```

If ports are busy:

```bash
OCTOFAN_MOCK=1 OCTOFAN_CONTROLLER_PORT=18000 PROMETHEUS_PORT=19090 GRAFANA_PORT=13000 docker compose up --build -d
```

## Stop

```bash
docker compose down
```

## Docker Group Without Reboot

If Docker permissions were just added and the shell has not been restarted:

```bash
newgrp docker
```

or for one command:

```bash
sg docker -c 'docker compose ps'
```

## Connect Ollama

The compose file includes an Ollama service. To enable controller polling:

```yaml
ollama:
  enabled: true
  base_url: http://ollama:11434
  timeout_seconds: 2.0
```

Restart the controller:

```bash
docker compose restart octofan-controller
```

If Ollama runs outside this compose project, connect that container to the stack network:

```bash
docker network connect octofan-ai ollama
```

Check Ollama:

```bash
curl -fsS http://localhost:11434/api/tags
```

## Watchdog

The watchdog is disabled by default. To enable it:

1. Set `watchdog.enabled: true`.
2. Configure `short_timeout_seconds` and `long_timeout_seconds`.
3. Add one or more checks.

Example TCP check for the host SSH service:

```yaml
watchdog:
  enabled: true
  short_timeout_seconds: 120
  long_timeout_seconds: 1500
  feed_interval_seconds: 5.0
  checks:
    - type: tcp
      target: host.docker.internal:22
      timeout_seconds: 1.0
```

If any check fails, the daemon does not feed the hardware watchdog.

## Fan Control

Auto mode uses the intake/internal sensor:

1. BME280 No. 0 temperature when present.
2. `Temperature No. 0` fallback.
3. First sane controller temperature fallback.

Impossible sensor values below `-20C` or above `120C` are ignored. If the controller cannot be read, fans are set to `fail_safe_percent`.

## OLED Display

The dynamic display refresh is controlled in `config/octofan.yaml`:

```yaml
display:
  refresh_interval_seconds: 15.0
  persist_to_eeprom: true
```

When `persist_to_eeprom` is true, the controller writes the static OLED layout to EEPROM once per process start/profile change, and whenever `POST /api/display/render` is called. Runtime values continue to refresh at the normal interval without rewriting EEPROM every cycle.

## Useful Checks

```bash
docker compose ps
curl -fsS http://localhost:8000/api/status
curl -fsS http://localhost:8000/metrics
curl -fsS 'http://localhost:9090/api/v1/query?query=octofan_controller_up'
curl -fsS http://admin:octofan@localhost:3000/api/health
```

## Hardware Notes

The container must be able to access USB. The compose file uses:

- `privileged: true`
- `/dev/bus/usb:/dev/bus/usb`

The controller and Ollama services also request `gpus: all` so the NVIDIA runtime can expose `nvidia-smi` and CUDA devices.

Keep the controller UI/API on a trusted LAN. v1 has no authentication.
