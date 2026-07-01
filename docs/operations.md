# Operations

## Start With Hardware

```bash
docker compose up --build -d
```

Open:

- Controller: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- RPC GPU 0: `localhost:5000`
- RPC GPU 1: `localhost:5001`
- RPC GPU 2: `localhost:5002`
- RPC GPU 3: `localhost:5003`

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

## llama.cpp RPC Bridge

This stack is the RPC server side on `octoserver.core.sied.ar`. It does not load models and does not query model APIs. The controller only checks that the four RPC TCP ports are reachable:

```yaml
rpc:
  enabled: true
  timeout_seconds: 1.0
  backends:
  - name: gpu0
    gpu: 0
    target: llamacpp-rpc-gpu0:5000
  - name: gpu1
    gpu: 1
    target: llamacpp-rpc-gpu1:5001
  - name: gpu2
    gpu: 2
    target: llamacpp-rpc-gpu2:5002
  - name: gpu3
    gpu: 3
    target: llamacpp-rpc-gpu3:5003
```

Restart the controller:

```bash
docker compose restart octofan-controller
```

The RPC containers are exposed externally as:

```text
octoserver.core.sied.ar:5000 -> GPU 0
octoserver.core.sied.ar:5001 -> GPU 1
octoserver.core.sied.ar:5002 -> GPU 2
octoserver.core.sied.ar:5003 -> GPU 3
```

Check RPC:

```bash
docker compose ps
nc -vz octoserver.core.sied.ar 5000
curl -fsS http://localhost:8000/metrics | grep octofan_rpc
```

The model APIs live on `aiworker.core.sied.ar` and are managed by `poc/llamacpp-rpc/node1/docker-compose.yml`.

Each RPC backend runs `/app/rpc-server` directly and is pinned to one NVIDIA device with Compose `device_ids`. Set `LLAMACPP_RPC_GPU*_DEVICE` or `LLAMACPP_RPC_GPU*_PORT` in the shell or `.env` before `docker compose up` to override mappings.

## Front LEDs

The controller can drive the Octofan front LEDs through `fan_controller_cli -l`.

Default mapping:

- LED `0`: orange warning/error.
- LED `1`: blue RPC/controller online.
- LED `2`: white GPU activity.

Enable LED control with:

```yaml
leds:
  enabled: true
  poll_interval_seconds: 1.0
  gpu_activity_utilization_percent: 15.0
  gpu_activity_power_watts: 40.0
```

The white activity LED uses NVIDIA utilization or power as an external signal. The controller does not intercept model requests.

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
  unhealthy_failures_before_reset: 3
  checks:
    - type: tcp
      target: host.docker.internal:22
      timeout_seconds: 1.0
```

If `enabled` is true and any check fails for `unhealthy_failures_before_reset` consecutive watchdog cycles, the daemon does not feed the hardware watchdog. Short transient check failures are tolerated so the USB controller is not reset by one missed TCP or HTTP probe. If `enabled` is false and `keepalive_when_disabled` is true, the daemon feeds the hardware watchdog without using it as a reset policy.

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

The controller only enters idle mode when `nvidia-smi` is healthy, all GPUs are below the configured utilization, power and temperature thresholds, and intake temperature is below the configured limit. Manual and automatic targets are clamped to `min_percent..max_percent`, so requests below the known active range do not produce misleading PWM targets. Any load, hotter temperature, missing GPU reading or controller read failure returns to the normal fan curve or fail-safe behavior.

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

The controller requests `gpus: all` so the NVIDIA runtime can expose `nvidia-smi`. Each llama.cpp service reserves a specific GPU with Compose `device_ids`.

`node-exporter` runs in the host network namespace. Without this, Linux network metrics would show the exporter container interface instead of the host NIC.

Keep the controller UI/API on a trusted LAN. v1 has no authentication.
