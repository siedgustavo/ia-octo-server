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

Ollama sees both NVIDIA GPUs through `gpus: all`. The service defaults to:

```env
OLLAMA_CONTEXT_LENGTH=65536
OLLAMA_KEEP_ALIVE=-1
OLLAMA_KV_CACHE_TYPE=q8_0
OLLAMA_NUM_PARALLEL=1
OLLAMA_SCHED_SPREAD=true
```

This spreads each model across both GPUs, halves KV-cache memory relative to `f16`, and keeps idle models resident. Both local models use 65k context windows so they satisfy Ollama's VRAM-headroom check simultaneously. When another model needs memory, Ollama queues the request and unloads idle models as necessary. API callers can override the policy per request with `keep_alive`.

Both local model definitions set `num_batch=128` and `repeat_penalty=1.0`. The batch setting reduces GPU compute-buffer usage for their large context windows. The repetition penalty setting matches the former llama.cpp behavior and avoids a measured twofold generation slowdown on these models.

Create the two local models from the existing read-only GGUF mount:

```bash
docker compose up -d ollama
docker compose exec ollama \
  ollama create qwen3coder:30b -f /model-definitions/qwen3coder.Modelfile
docker compose exec ollama \
  ollama create qwen3.6:35b -f /model-definitions/qwen36-uncensored.Modelfile
```

Inspect models stored on disk and models currently occupying memory:

```bash
curl -fsS http://localhost:11434/api/tags
curl -fsS http://localhost:11434/api/ps
docker compose exec ollama ollama list
docker compose exec ollama ollama ps
```

Add experimental models with `docker compose exec ollama ollama pull <model>`. Ollama can use both RTX 3090 cards and unload idle models when another request needs their VRAM.

## ComfyUI Image Generation

The optional `comfyui` service is exposed on port `8188` and is disabled by default through the `imagegen` profile. It defaults to GPU 1, so avoid running it alongside a memory-intensive inference workload on that GPU:

```bash
docker compose --profile imagegen up -d comfyui
curl -fsS http://localhost:8188/system_stats
```

Runtime data is kept outside the repo:

```env
COMFYUI_MODELS_DIR=/opt/imagegen/comfyui/models
COMFYUI_OUTPUT_DIR=/opt/imagegen/comfyui/output
COMFYUI_CUSTOM_NODES_DIR=/opt/imagegen/comfyui/custom_nodes
```

For a Chroma FP8 workflow, use these model locations:

```text
/opt/imagegen/comfyui/models/diffusion_models/Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors
/opt/imagegen/comfyui/models/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors
/opt/imagegen/comfyui/models/clip/t5xxl_fp8_e4m3fn_scaled.safetensors -> ../text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors
/opt/imagegen/comfyui/models/vae/ae.safetensors
```

Suggested downloads:

```bash
mkdir -p /opt/imagegen/comfyui/models/diffusion_models \
  /opt/imagegen/comfyui/models/text_encoders \
  /opt/imagegen/comfyui/models/clip \
  /opt/imagegen/comfyui/models/vae

curl -L --fail --continue-at - \
  -o /opt/imagegen/comfyui/models/diffusion_models/Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors \
  https://huggingface.co/silveroxides/Chroma1-HD-fp8-scaled/resolve/main/Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors

curl -L --fail --continue-at - \
  -o /opt/imagegen/comfyui/models/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors \
  https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors

ln -sfn ../text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors \
  /opt/imagegen/comfyui/models/clip/t5xxl_fp8_e4m3fn_scaled.safetensors

curl -L --fail --continue-at - \
  -o /opt/imagegen/comfyui/models/vae/ae.safetensors \
  https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors
```

ComfyUI is not part of the controller's AI health model yet; use the ComfyUI UI/API directly while image workflows are experimental.

## Front LEDs

The controller can drive the Octofan front LEDs through `fan_controller_cli -l`.

Default mapping:

- LED `0`: orange warning/error.
- LED `1`: blue llama.cpp online.
- LED `2`: white GPU activity.

Enable LED control with:

```yaml
leds:
  enabled: true
  poll_interval_seconds: 1.0
  gpu_activity_utilization_percent: 15.0
  gpu_activity_power_watts: 40.0
```

The white activity LED uses NVIDIA utilization or power as an external signal. The controller does not intercept llama.cpp requests.

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

The controller only enters idle mode when `nvidia-smi` is healthy, all GPUs are below the configured utilization, power and temperature thresholds, llama.cpp is not generating, and intake temperature is below the configured limit. Manual and automatic targets are clamped to `min_percent..max_percent`, so requests below the known active range do not produce misleading PWM targets. Any load, hotter temperature, missing GPU reading or controller read failure returns to the normal fan curve or fail-safe behavior.

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
