# Octofan AI Server

Container stack for reusing an Octominer/Octofan chassis as an AI inference server enclosure.

The stack keeps the original `fan_controller_cli` binary as the hardware interface and replaces the HiveOS scripts with a Python/FastAPI controller, Prometheus metrics, and a provisioned Grafana dashboard.

The original HiveOS package files are preserved only as reference material under `reference/octofan-hiveos-originals/`.

## What It Does

- Reads Octofan controller telemetry through the original USB CLI.
- Controls chassis fans from internal case temperature.
- Exposes all controller telemetry as Prometheus metrics.
- Adds NVIDIA GPU telemetry from `nvidia-smi`.
- Adds host CPU, memory, disk and network telemetry through node exporter.
- Ships Grafana dashboards for overview, PSUs, environment, cooling, GPUs, host/network, watchdog and AI metrics.
- Updates the controller OLED with host, thermal, power and AI status.
- Drives the front-panel LEDs from controller health and GPU activity.
- Feeds the hardware watchdog only when configured host checks pass.
- Runs Ollama with both NVIDIA GPUs visible and on-demand model scheduling.

## Services

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage.
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).
- `ollama`: on-demand Ollama API at `http://localhost:11434`, with both GPUs visible.
- `comfyui`: optional ComfyUI image generation workspace at `http://localhost:8188`.

## Repository Layout

- `controller/`: Python FastAPI controller service.
- `config/octofan.yaml`: mounted runtime configuration.
- `grafana/`: provisioned datasource and dashboard.
- `prometheus/prometheus.yml`: scrape configuration.
- `reference/octofan-hiveos-originals/`: original HiveOS files retained for reference.
- `tests/`: parser, control, display and API tests.

## Quick Start

Optional: copy `.env.example` to `.env` and adjust ports or mock mode.

```bash
docker compose up --build
```

Open:

- Controller UI: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Ollama: `http://localhost:11434`

Grafana provisions these dashboards under the `Octofan` folder:

- `Octofan - Overview`
- `Octofan - Power Supplies`
- `Octofan - Environment`
- `Octofan - Cooling`
- `Octofan - GPUs`
- `Octofan - Host and Network`

To test without Octofan hardware:

```bash
OCTOFAN_MOCK=1 docker compose up --build
```

If the default UI ports are already in use:

```bash
OCTOFAN_MOCK=1 OCTOFAN_CONTROLLER_PORT=18000 PROMETHEUS_PORT=19090 GRAFANA_PORT=13000 docker compose up --build
```

## AlmaLinux 10 Notes

The controller container is privileged and mounts `/dev/bus/usb` because the original CLI uses libusb to talk to the Octofan controller. Keep the stack on a trusted LAN; v1 intentionally has no authentication on the controller UI/API.

Configuration lives in `config/octofan.yaml`.

## Configuration

The controller watches the mounted YAML at startup. Restart `octofan-controller` after manual edits:

```bash
docker compose restart octofan-controller
```

Important sections:

- `fans`: auto/manual mode, target temperature, min/max fan limits and fail-safe speed.
- `watchdog`: hardware watchdog timeouts and HTTP/TCP health checks.
- `display`: OLED profile and refresh interval.
- `leds`: front-panel LED policy. By default LED `0` is orange warning, LED `1` is blue online and LED `2` is white activity.
- `llamacpp`: legacy controller polling support; disabled in the active stack.

The fan controller uses BME280 sensor `0` as intake/internal temperature when available, then falls back to `Temperature No. 0`.

`fans.gpu_idle_stop_enabled` can hold the chassis fans at the lowest active configured speed while NVIDIA GPUs are idle and cool. Manual and automatic targets are clamped to `fans.min_percent..fans.max_percent`, and the idle policy falls back to the normal auto curve when GPU load, GPU temperature, intake temperature or telemetry health no longer matches the configured idle thresholds.

## API

- `GET /api/status`
- `GET /api/config`
- `PUT /api/config`
- `POST /api/fans/manual`
- `POST /api/fans/auto`
- `POST /api/display/render`
- `POST /api/watchdog/test`
- `POST /api/calibrate-fans`
- `GET /metrics`

## Ollama

The stack includes one Ollama instance with both NVIDIA GPUs visible. It processes one request per model in parallel, spreads every model across both GPUs, uses an 8-bit KV cache so both local models fit with 65k context windows, and uses `OLLAMA_KEEP_ALIVE=-1` so idle models remain resident until the scheduler needs their memory for another model.

Ollama stores its model inventory under `${OLLAMA_DATA_DIR:-/opt/ollama}`. The two existing GGUF files can be registered without downloading them again:

```bash
docker compose up -d ollama
docker compose exec ollama ollama create qwen3coder:30b -f /model-definitions/qwen3coder.Modelfile
docker compose exec ollama ollama create qwen3.6:35b -f /model-definitions/qwen36-uncensored.Modelfile
docker compose exec ollama ollama list
```

The imported models use their tuned context sizes, `num_batch=128` to reduce inference compute buffers on the 24 GiB GPUs, and `repeat_penalty=1.0` to avoid the large sampler overhead measured with these 248k-token vocabularies. Other models can be added with `ollama pull`, and Ollama loads them only when requested:

```bash
docker compose exec ollama ollama pull gemma3
curl http://localhost:11434/api/chat -d '{
  "model": "gemma3",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false
}'
docker compose exec ollama ollama ps
```

The scheduler can distribute a model across both GPUs and unload idle models when another request needs their VRAM.

## Image Generation

The compose stack includes an optional ComfyUI workspace exposed at `http://localhost:8188`. Start it explicitly with `docker compose --profile imagegen up -d comfyui`; it defaults to GPU 1 and should not run alongside a memory-intensive inference workload on that GPU.

Persistent directories live under `${COMFYUI_MODELS_DIR:-/opt/imagegen/comfyui/models}` and sibling paths for cache, input, output, user data and custom nodes. For Chroma/Flux-style workflows, place files in:

- `diffusion_models/`: Chroma checkpoint, for example `Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors`.
- `text_encoders/`: T5 XXL text encoder, for example `t5xxl_fp8_e4m3fn_scaled.safetensors`.
- `clip/`: compatibility symlink to the same T5 file for workflows that still look under `models/clip`.
- `vae/`: Flux VAE, for example `ae.safetensors`.

ComfyUI is intentionally not polled by `octofan-controller` yet. Use it directly through the ComfyUI web UI or API while workflows are experimental.

## Validation

Run tests locally:

```bash
python3 -m venv .venv
.venv/bin/pip install -r controller/requirements.txt pytest
.venv/bin/python -m pytest -q
```

Validate the compose file:

```bash
docker compose config
```

Test the full stack without hardware:

```bash
OCTOFAN_MOCK=1 docker compose up --build
```

## Documentation

- [Architecture](docs/architecture.md)
- [Operations](docs/operations.md)
- [API and metrics](docs/api-and-metrics.md)
