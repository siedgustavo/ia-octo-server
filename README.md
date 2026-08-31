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
- Runs Ollama with every NVIDIA GPU visible and on-demand model scheduling.

## Services

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage.
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).
- `ollama`: on-demand Ollama API at `http://localhost:11434`, with every host GPU visible.

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
- `llamacpp`: optional legacy health polling; disabled when Ollama is the only inference service.
- `ollama`: on-demand inference health polling (`enabled`, `base_url`, `timeout_seconds`). When enabled, the controller polls Ollama and reflects it in `/api/status`, the OLED `ai` profile and the online/warning LEDs.

Automatic fan control combines BME280 intake, exhaust, exhaust-minus-intake delta and a capped
hottest-GPU assistance curve, then applies the highest demand. Chassis temperatures govern normal
airflow; GPU temperature only contributes above 75C and cannot request more than 40% before the
88C emergency threshold. Invalid sensors are filtered independently, while critical temperatures
override normal slew limits. The API, Prometheus and Cooling dashboard expose each signal's demand.

`fans.gpu_idle_stop_enabled` can hold the chassis fans at the lowest active configured speed while NVIDIA GPUs are idle and cool. Manual and automatic targets are clamped to `fans.min_percent..fans.max_percent`, and the idle policy falls back to the normal auto curve when GPU load, GPU temperature, intake temperature or telemetry health no longer matches the configured idle thresholds.

The OLED `ai` profile shows the host IP, AI health (`Ollama N models loaded`, `Ollama DOWN`, `AI services OK` or `AI monitor off`), hottest-GPU temperature and load, intake temperature with the current fan percent, and total power. The host IP is auto-detected from the host hostname and `/etc/hosts` (both mounted read-only into the controller); set `OCTOFAN_DISPLAY_IP` in `.env` to pin a specific address.

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

The stack includes one Ollama instance with every NVIDIA GPU on the host visible. It processes one request
per model in parallel, packs a model into one GPU whenever it fits, uses a 4-bit KV cache to
reduce context memory, and uses `OLLAMA_KEEP_ALIVE=3h` so models unload after three hours without
requests. Request-level `keep_alive` can override this default. Models that do not fit in one card are still
split across the available GPUs automatically. Compose uses `gpus: all`, so adding or removing a card does
not require maintaining a list of GPU indices.

Ollama stores its active model inventory under `${OLLAMA_DATA_DIR:-/opt/ollama}`. Cold GGUF files live under `${MODELS_ARCHIVE_DIR:-/opt/models-archive}`, mounted read-only at `/models-archive`, and can be registered without downloading them again:

```bash
docker compose up -d ollama
docker compose exec ollama ollama create qwen3coder:30b -f /model-definitions/qwen3coder.Modelfile
docker compose exec ollama ollama create qwen3.6:35b -f /model-definitions/qwen36-uncensored.Modelfile
docker compose exec ollama ollama list
```

Each installed model pins its context in its own manifest; there is no container-wide context override. Interactive models use their native maximum and are never configured below 128k. The dedicated `mistral-medium-3.5:128b` writing model is the exception: sied-poster caps scraped input at 8,000 characters and requests at most 4,096 output tokens, so its IQ2_S manifest uses 32k to keep more layers on the GPUs. The imported Qwen models also use `num_batch=128` and `repeat_penalty=1.0` to avoid the large sampler overhead measured with their 248k-token vocabularies. The local Ollama 0.32.13 image removes the scheduler's conservative 20% VRAM reserve for model admission and single-GPU placement, and makes that estimate honor the configured quantized KV cache and recurrent layers. A model therefore stays on one card whenever its complete predicted allocation fits. Other models can be added with `ollama pull`, and Ollama loads them only when requested:

```bash
docker compose exec ollama ollama pull gemma3
curl http://localhost:11434/api/chat -d '{
  "model": "gemma3",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false
}'
docker compose exec ollama ollama ps
```

The scheduler can distribute a model across all visible GPUs and unload idle models when another request needs their VRAM.

The installed inventory uses only `name:parameter-count` tags:

```bash
qwen36-fable:27b
deepseek-v4-flash:284b
mistral-medium-3.5:128b
qwen3-coder-next:80b
qwen3coder:30b
qwen3.6:35b
```

`deepseek-v4-flash:284b` uses Unsloth's `UD-Q8_K_XL` quantization of the 0731
checkpoint and pins its native 1,048,576-token context. Its roughly 162 GB of
weights are staged under `/opt/models-archive/deepseek-v4-flash-0731` for
Ollama's multi-file GGUF import. They require all four GPUs plus host RAM, so
expect partial CPU offload.

Reapply a model's configured context through a temporary manifest without changing its stable tag:

```bash
docker compose exec ollama ollama create qwen3-coder-next:configured \
  -f /model-definitions/qwen3-coder-next-80b.Modelfile
docker compose exec ollama ollama cp qwen3-coder-next:configured qwen3-coder-next:80b
docker compose exec ollama ollama rm qwen3-coder-next:configured
```

When weights plus KV cache do not fit on one GPU, Ollama spreads the GPU-resident portion across
the visible cards and offloads the remainder to host RAM. Loading this
model can evict the smaller resident models; benchmark it before routing production traffic.

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
- [GLM-5.3-Flash tuning and lessons](docs/glm53flash-benchmark.md)
- [Qwen3.8-Flash-Next split benchmark](docs/qwen38flash-split-benchmark.md)
- [Hardware mods](docs/hardware-mods.md)
- [Watchdog power cycle (Plan B)](docs/watchdog-power-cycle.md)
