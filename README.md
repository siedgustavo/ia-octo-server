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
- Drives the front-panel LEDs for llama.cpp health and GPU activity.
- Feeds the hardware watchdog only when configured host checks pass.
- Integrates with GPU-pinned llama.cpp containers over Docker networking.

## Services

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage.
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).
- `llama-server-*`: OpenAI-compatible llama.cpp APIs at `http://localhost:8080` through `http://localhost:8083`.

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
- `ai`: llama.cpp/OpenAI-compatible inference endpoints.

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

## llama.cpp

Enable `ai.enabled` in `config/octofan.yaml` and point `ai.base_urls` to the llama.cpp servers. The OLED and Grafana dashboard include model inventory from `/v1/models`.

Tokens per second remain unavailable from controller-side polling. To expose exact token throughput without changing traffic flow, instrument the application that calls the OpenAI-compatible APIs and export that data separately.

The compose stack includes one prebuilt `llama-server` container per model. Production uses GPUs 0-2; GPU 3 is reserved for the optional `playground` profile:

```yaml
ai:
  enabled: true
  source: llamacpp
  base_url: http://llama-server-qwen3coder:8080
  base_urls:
  - http://llama-server-qwen3coder:8080
  - http://llama-server-qwen36-uncensored:8080
  - http://llama-server-llama31-pro:8080
  timeout_seconds: 2.0
```

Externally, the model servers are exposed as `8080` through `8082`; `8083` is reserved for playground.

Default model paths are configurable through environment variables:

```env
MODELS_DIR=/modelos
QWEN3CODER_GGUF=/modelos/qwen3coder-35b.gguf
QWEN36_UNCENSORED_GGUF=/modelos/qwen3.6-uncensored.gguf
LLAMA31_PRO_GGUF=/modelos/llama3.1-pro.gguf
PLAYGROUND_GGUF=/modelos/playground.gguf
```

Each llama.cpp service reserves one NVIDIA device with Docker Compose `device_ids`, so NVIDIA Container Toolkit must be available on the host.

The compose services set per-model context windows to `32768` by default. Override `QWEN3CODER_CTX_SIZE`, `QWEN36_UNCENSORED_CTX_SIZE`, `LLAMA31_PRO_CTX_SIZE` or `PLAYGROUND_CTX_SIZE` before starting the stack if a different context window is needed.

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
