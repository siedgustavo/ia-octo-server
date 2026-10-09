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

## Monitoring Retention

Prometheus keeps local history in the `prometheus-data` Docker volume. The compose file limits retention by both time and size; whichever limit is reached first wins:

```env
PROMETHEUS_RETENTION_TIME=15d
PROMETHEUS_RETENTION_SIZE=2GB
```

Set these in `.env` before starting the stack if you need a different history window or disk cap.

## Docker Group Without Reboot

If Docker permissions were just added and the shell has not been restarted:

```bash
newgrp docker
```

or for one command:

```bash
sg docker -c 'docker compose ps'
```

## Ollama On-Demand Models

Ollama sees every NVIDIA GPU through `gpus: all`. The service defaults to:

```env
OLLAMA_KEEP_ALIVE=-1
OLLAMA_KV_CACHE_TYPE=q4_0
OLLAMA_NUM_PARALLEL=1
OLLAMA_SCHED_SPREAD=false
```

This packs a model into one GPU whenever its weights, context and compute buffers fit within 80%
of free VRAM, and only splits it across multiple GPUs when necessary. The 4-bit KV cache quarters
KV-cache memory relative to `f16`, while `OLLAMA_KEEP_ALIVE=-1` keeps loaded models resident until
VRAM pressure requires eviction. Context is pinned in each model manifest to that model's native maximum; there is
deliberately no container-wide context override. Operational context must never be lower than
128k even when the larger context reduces throughput. The main Ollama service runs the reproducible
custom `0.35.1-b11381` image, accepting its built-in scheduler headroom:
the stock binary reserves 20% of free VRAM before admitting a model or picking a single GPU, and
that threshold is not configurable. This repo previously built a patched binary from source to
remove that reserve, but Ollama's internal GGUF-reading API changed enough between releases
(the `ggml` package backing `PredictServerVRAM`'s `GraphSize` call was replaced by a new `fs/gguf`
package with no equivalent) that re-porting the patch on every upgrade became fragile and risky to
get subtly wrong. Models that need disk-persisted KV slot caching still run as dedicated `llama.cpp`
containers instead — see `docker-compose.qwen38flash.yml` and `docker-compose.glm53flash.yml`.
Qwen3.8-Flash-Next uses the main Ollama service with its asymmetric layer split and independent
ubatch configured in its manifest. When another
model truly needs memory, Ollama queues the request and unloads idle models as necessary. API
callers can override the residency policy per request with `keep_alive`. A request-level value of
zero can release a model immediately; a negative value intentionally requests indefinite residency.


Both local model definitions set `num_batch=128` and `repeat_penalty=1.0`. The batch setting reduces GPU compute-buffer usage for their large context windows. The repetition penalty setting matches the former llama.cpp behavior and avoids a measured twofold generation slowdown on these models.

> **Never use `docker compose up --remove-orphans` from the main `docker-compose.yml` while the
> dedicated Qwen/GLM `llama.cpp` stacks (`docker-compose.qwen38flash.yml`,
> `docker-compose.glm53flash.yml`) are running.** Those containers live in the same Compose
> project namespace but are started from separate compose files, so the main project considers
> them orphans and `--remove-orphans` will stop and remove them. This has happened in production:
> recreating `ollama` with `--remove-orphans` silently deleted the running `qwen38flash`
> container. If you need to recreate a single service, target it explicitly without that flag
> (`docker compose up -d --force-recreate ollama`), or stop and restart the other stacks
> deliberately if cleanup is actually needed.

Create local models from the read-only archive mount. Importing registers an active Ollama copy while preserving the cold GGUF in `/opt/models-archive`. DeepSeek V4 Flash below is the current example of this workflow.

On an existing installation, rebuild temporary aliases from the registered models and then copy
them back onto the stable names. This updates only manifests and reuses the stored blobs:

```bash
docker compose exec ollama ollama create qwen3-coder-next:configured \
  -f /model-definitions/qwen3-coder-next-80b.Modelfile
docker compose exec ollama ollama cp qwen3-coder-next:configured qwen3-coder-next:80b
docker compose exec ollama ollama rm qwen3-coder-next:configured
```

Inspect models stored on disk and models currently occupying memory:

```bash
curl -fsS http://localhost:11434/api/tags
curl -fsS http://localhost:11434/api/ps
docker compose exec ollama ollama list
docker compose exec ollama ollama ps
```

Add experimental models with `docker compose exec ollama ollama pull <model>`. Ollama can use every host GPU and unload idle models when another request needs their VRAM.

Production model tags follow `name:parameter-count`:

```bash
deepseek-v4-flash:284b
mistral-medium-3.5:128b
qwen3-coder-next:80b
qwen3.8:27b-q8_0
qwen3.8-flash-next:176b
```


DeepSeek V4 Flash uses the Unsloth 0731 `UD-Q8_K_XL` GGUF and its native
1,048,576-token context. The approximately 162 GB model cannot fit entirely in
the four RTX 3090 GPUs and therefore uses host RAM for partial CPU offload. Its
five GGUF shards are staged in `/opt/models-archive/deepseek-v4-flash-0731`
and imported by Ollama through the archive's read-only container mount.

Because Ollama's registry pull does not support sharded GGUF repositories, import
the directory first, then apply the configured manifest. Keep the imported tag
and archive shards so the model remains reproducible without another download:

```bash
docker compose exec --workdir /models-archive/deepseek-v4-flash-0731/UD-Q8_K_XL \
  ollama ollama create deepseek-v4-flash:imported
docker compose exec ollama ollama create deepseek-v4-flash:284b \
  -f /model-definitions/deepseek-v4-flash-284b.Modelfile
```

This 51 GB quantization may require multi-GPU placement or partial CPU offload. Check
`ollama ps`, `nvidia-smi` and `free -h` during the first benchmark before exposing it through
the router.

Each tag has a dedicated manifest. Interactive models pin their native context; the
`mistral-medium-3.5:128b` IQ2_S writing model uses 32k for sied-poster. Reapply a manifest
through a temporary tag so the stable name remains available:

```bash
docker compose exec ollama ollama create mistral-medium-3.5:configured \
  -f /model-definitions/mistral-medium-3.5-128b.Modelfile
docker compose exec ollama ollama cp mistral-medium-3.5:configured mistral-medium-3.5:128b
docker compose exec ollama ollama rm mistral-medium-3.5:configured
docker compose exec ollama ollama create qwen3-coder-next:configured \
  -f /model-definitions/qwen3-coder-next-80b.Modelfile
docker compose exec ollama ollama cp qwen3-coder-next:configured qwen3-coder-next:80b
docker compose exec ollama ollama rm qwen3-coder-next:configured
docker compose exec ollama ollama create qwen3.8:configured \
  -f /model-definitions/qwen38-27b-q8_0.Modelfile
docker compose exec ollama ollama cp qwen3.8:configured qwen3.8:27b-q8_0
docker compose exec ollama ollama rm qwen3.8:configured
docker compose exec ollama ollama create deepseek-v4-flash:configured \
  -f /model-definitions/deepseek-v4-flash-284b.Modelfile
docker compose exec ollama ollama cp deepseek-v4-flash:configured deepseek-v4-flash:284b
docker compose exec ollama ollama rm deepseek-v4-flash:configured
docker compose exec ollama ollama create qwen3.8-flash-next:176b \
  -f /model-definitions/qwen3.8-flash-next.Modelfile
```

## Front LEDs

The controller can drive the Octofan front LEDs through `fan_controller_cli -l`.

Default mapping:

- LED `0`: orange warning/error.
- LED `1`: blue controller/optional AI health online.
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
  unhealthy_failures_before_reset: 3
  checks:
    - type: tcp
      target: host.docker.internal:22
      timeout_seconds: 1.0
```

If `enabled` is true and any check fails for `unhealthy_failures_before_reset` consecutive watchdog cycles, the daemon does not feed the hardware watchdog. Short transient check failures are tolerated so the USB controller is not reset by one missed TCP or HTTP probe. If `enabled` is false and `keepalive_when_disabled` is true, the daemon feeds the hardware watchdog without using it as a reset policy.

### Hardware escalation (firmware-level)

The escalation below runs entirely in the Octofan board firmware over its connection to the
motherboard front-panel headers. It works even if the OS is hung, sshd is dead, or the machine
has kernel-panicked: no software on the host participates once the watchdog is armed.

| Timeout | Config key | Board action |
| --- | --- | --- |
| Short | `short_timeout_seconds` | Pulse the motherboard **RESET** header (hardware reset, independent of the OS). |
| Long | `long_timeout_seconds` | The firmware drives **PWR SW**, but this line is disconnected in production. It cannot recover a host that remains stuck after RESET. |

Current production values: short `120s`, long `1500s`. With `feed_interval_seconds: 30` and
`unhealthy_failures_before_reset: 3`, a hung host (SSH check failing) stops being fed after
~90-120s. If the Octofan remains powered and armed, the short timeout pulses RESET. The long
timeout cannot power-cycle this production host; use the smart plug to cut AC power if RESET
does not recover it. See [the current wiring and power-cycle procedure](watchdog-power-cycle.md).

Limits:

- The board cannot cut mains power. Production uses a SmartLife/Tuya smart plug for AC
  power cycling, with power recovery set to ON.
- The watchdog state lives in the board. If the controller container dies while the watchdog is
  armed, the board escalates on its own. Use `keepalive_when_disabled: true` when intentionally
  disabling the reset policy so a stopped/unhealthy controller does not trip the board.
- The `octofan-poc-safety.service` systemd unit (legacy llama.cpp RPC POC loop) is disabled and
  must stay disabled: two feeders on the same USB device race and mask real watchdog events.

Inspect the live board state (armed mode and cumulative reset counter) with:

```bash
docker exec octofan-controller /opt/octofan/fan_controller_cli -h | grep -i watch
# Watch-Dog Mode: 2    Reset Counter = 19
```

`Watch-Dog Mode` is `0` when disarmed and non-zero when armed. `Reset Counter` is cumulative in
firmware and includes resets from the HiveOS era of this board.

## Fan Control

Auto mode calculates independent demand from intake, exhaust, their positive temperature delta
and the hottest NVIDIA GPU, then uses the highest demand. Production uses these curves:

| Signal | Quiet minimum | Curve maximum | Immediate critical |
| --- | ---: | ---: | ---: |
| Intake | <=30C at 10% | 40C at 100% | 45C |
| Exhaust | <=30C at 10% | 45C at 100% | 50C |
| Exhaust - intake | <=7C at 10% | 18C at 100% | 22C |
| Hottest GPU | <=45C at 10% | 70C at 85% | 88C |

Between each pair of points, demand is interpolated linearly. Intake, exhaust and delta can request
the full configured range. The GPU curve starts early because the middle GPU reached 80C and 95%
onboard fan speed while the chassis target was only 34%. At 55C, 60C and 65C the GPU requests
40%, 55% and 70% chassis fan speed respectively. The 85% cap applies from 70C to the critical
threshold of 88C, which immediately requests 100%. Normal increases are limited by
`max_step_percent` per poll;
decreases use the slower `max_down_step_percent`. Changes within `target_deadband_percent` are
ignored. Crossing any critical threshold immediately selects `max_percent` without slew limiting.

Intake prefers BME280 No. 0 and exhaust prefers BME280 No. 1 or `Temperature No. 1`, with sane
fallbacks. Temperatures below `-20C` or above `120C` are ignored. If the controller cannot be read
or no thermal signal remains, fans ramp toward `fail_safe_percent`; setting `fail_safe_ramp: false`
makes that transition immediate. GPU telemetry failure does not force full speed while valid
intake/exhaust sensors remain available.

The API exposes the complete decision as `fan_control`. Prometheus exports pre-slew demands as
`octofan_fan_control_target_percent{source="intake|exhaust|delta|gpu|combined"}`, shown in the Cooling
dashboard's `Automatic Policy Demand` panel.

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

The controller only enters idle mode when `nvidia-smi` is healthy, all GPUs are below the configured utilization, power and temperature thresholds, llama.cpp is not generating, and intake temperature is below the configured limit. Manual and automatic targets are clamped to `min_percent..max_percent`, so requests below the known active range do not produce misleading PWM targets. Any load, hotter temperature, missing GPU reading or controller read failure returns to the normal fan curve or fail-safe behavior.

## OLED Display

The dynamic display refresh is controlled in `config/octofan.yaml`:

```yaml
display:
  refresh_interval_seconds: 15.0
  persist_to_eeprom: true
```

When `persist_to_eeprom` is true, the controller writes the static OLED layout to EEPROM once per process start/profile change, and whenever `POST /api/display/render` is called. Runtime values continue to refresh at the normal interval without rewriting EEPROM every cycle.

The `ai` profile prints the host IP on its first line. The controller resolves it from the host
hostname and `/etc/hosts` (both mounted read-only from the host); set `OCTOFAN_DISPLAY_IP` in `.env`
to override the detected address.

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

The controller and Ollama request `gpus: all`: the controller uses it for `nvidia-smi`, while Ollama can schedule models across every installed GPU without a maintained index list.

`node-exporter` runs in the host network namespace. Without this, Linux network metrics would show the exporter container interface instead of the host NIC.

Keep the controller UI/API on a trusted LAN. v1 has no authentication.
