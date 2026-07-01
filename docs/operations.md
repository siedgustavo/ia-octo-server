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

The compose file includes one Ollama service per GPU. To enable controller polling across all instances:

```yaml
ollama:
  enabled: true
  base_url: http://ollama-gpu0:11434
  base_urls:
  - http://ollama-gpu0:11434
  - http://ollama-gpu1:11434
  - http://ollama-gpu2:11434
  - http://ollama-gpu3:11434
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
curl -fsS http://localhost:11435/api/tags
curl -fsS http://localhost:11436/api/tags
curl -fsS http://localhost:11437/api/tags
```

The Ollama containers use GPU-specific context windows:

```yaml
OLLAMA_GPU0_CONTEXT_LENGTH: "49152"
OLLAMA_GPU1_CONTEXT_LENGTH: "40960"
OLLAMA_GPU2_CONTEXT_LENGTH: "32768"
OLLAMA_GPU3_CONTEXT_LENGTH: "32768"
```

It also keeps the last used model loaded by default:

```yaml
OLLAMA_KEEP_ALIVE: "-1"
```

It also keeps Ollama in pack scheduling mode:

```yaml
OLLAMA_SCHED_SPREAD: "false"
OLLAMA_MAX_LOADED_MODELS: "1"
```

Each service is pinned to one NVIDIA device with Compose `device_ids`, so selecting ports `11434` through `11437` selects GPU 0 through GPU 3. `OLLAMA_MAX_LOADED_MODELS=1` keeps one resident model per instance. Set `OLLAMA_GPU*_CONTEXT_LENGTH`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_MAX_LOADED_MODELS` or `OLLAMA_SCHED_SPREAD` in the shell or `.env` before `docker compose up` to override those defaults.

Ollama token throughput is not available from `/api/tags` or `/api/ps`. The controller keeps `octofan_ai_tokens_per_second_available` at `0` unless the application that calls Ollama exports request-level token telemetry through another integration.

## Front LEDs

The controller can drive the Octofan front LEDs through `fan_controller_cli -l`.

Default mapping:

- LED `0`: orange warning/error.
- LED `1`: blue Ollama online.
- LED `2`: white GPU activity.

Enable LED control with:

```yaml
leds:
  enabled: true
  poll_interval_seconds: 1.0
  gpu_activity_utilization_percent: 15.0
  gpu_activity_power_watts: 40.0
```

The white activity LED uses NVIDIA utilization or power as an external signal. The controller does not intercept Ollama requests.

## Watchdog

The watchdog reset policy is disabled by default, but `keepalive_when_disabled` is enabled so an Octofan controller with an already-armed hardware watchdog does not periodically reset/re-enumerate its USB device.

To enable host-health watchdog resets:

1. Set `watchdog.enabled: true`.
2. Configure `short_timeout_seconds` and `long_timeout_seconds`.
3. Add one or more checks.

Example TCP check for the host SSH service:

```yaml
watchdog:
  enabled: true
  keepalive_when_disabled: true
  short_timeout_seconds: 120
  long_timeout_seconds: 1500
  feed_interval_seconds: 5.0
  checks:
    - type: tcp
      target: host.docker.internal:22
      timeout_seconds: 1.0
```

If `enabled` is true and any check fails, the daemon does not feed the hardware watchdog. If `enabled` is false and `keepalive_when_disabled` is true, the daemon feeds the hardware watchdog without using it as a reset policy.

## Fan Control

Auto mode uses the intake/internal sensor:

1. BME280 No. 0 temperature when present.
2. `Temperature No. 0` fallback.
3. First sane controller temperature fallback.

Impossible sensor values below `-20C` or above `120C` are ignored. If the controller cannot be read or no sane temperature is available, fans ramp toward `fail_safe_percent` by `max_step_percent` per poll while `fail_safe_ramp` is enabled. Set `fail_safe_ramp: false` to jump directly to `fail_safe_percent`.

To let the chassis fans settle at the lowest active speed while GPUs are idle, enable the GPU idle policy and set `min_percent` to the measured hardware floor:

```yaml
fans:
  mode: auto
  min_percent: 10
  gpu_idle_stop_enabled: true
  gpu_idle_stop_percent: 10
  gpu_idle_stop_delay_seconds: 300.0
  gpu_idle_utilization_percent: 5.0
  gpu_idle_power_watts: 25.0
  gpu_idle_max_gpu_temp_c: 45.0
  gpu_idle_max_intake_temp_c: 35.0
```

The controller only enters idle mode when `nvidia-smi` is healthy, all GPUs are below the configured utilization, power and temperature thresholds, Ollama is not generating, and intake temperature is below the configured limit. Manual and automatic targets are clamped to `min_percent..max_percent`, so requests below the known active range do not produce misleading PWM targets. Any load, hotter temperature, missing GPU reading or controller read failure returns to the normal fan curve or fail-safe behavior.

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
curl -fsS 'http://localhost:9090/api/v1/query?query=rate(node_network_receive_bytes_total[2m])'
curl -fsS http://admin:octofan@localhost:3000/api/health
```

## Hardware Notes

The container must be able to access USB. The compose file uses:

- `privileged: true`
- `/dev/bus/usb:/dev/bus/usb`

The controller requests `gpus: all` so the NVIDIA runtime can expose `nvidia-smi`. Each Ollama service reserves a specific GPU with Compose `device_ids`.

`node-exporter` runs in the host network namespace. Without this, Linux network metrics would show the exporter container interface instead of the host NIC.

Keep the controller UI/API on a trusted LAN. v1 has no authentication.
