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
- Runs three GPU-pinned `llama-server` containers over Docker networking.

## Services

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage.
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).
- `llamacpp-qwen3coder`: llama.cpp OpenAI-compatible API at `http://localhost:8080`.
- `llamacpp-qwen36-uncensored`: llama.cpp OpenAI-compatible API at `http://localhost:8081`.
- `llamacpp-llama31-pro`: llama.cpp OpenAI-compatible API at `http://localhost:8082`.

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
- `llamacpp`: GPU-pinned llama.cpp endpoints.

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

Enable `llamacpp.enabled` in `config/octofan.yaml`. The controller polls each configured server with `/health`, `/props` and `/slots`; the OLED and Grafana dashboard show healthy models and active generation slots.

Tokens per second remain unavailable from controller-side polling, so `octofan_ai_tokens_per_second_available{source="llamacpp"}` stays `0` unless request-level telemetry is added separately.

The compose stack includes three direct `llama-server` services on the same Docker network:

```yaml
llamacpp:
  enabled: true
  timeout_seconds: 2.0
  servers:
  - name: qwen3coder:30b
    gpu: '0'
    base_url: http://llamacpp-qwen3coder:8080
    expected_model: qwen3coder:30b
  - name: qwen3.6:35b
    gpu: '1'
    base_url: http://llamacpp-qwen36-uncensored:8080
    expected_model: qwen3.6:35b
  - name: llama3.1:8b
    gpu: '2'
    base_url: http://llamacpp-llama31-pro:8080
    expected_model: llama3.1:8b
```

Externally, the GPU-pinned instances are exposed as `8080`, `8081` and `8082`. GPU 3 is intentionally left free.

Models are expected as GGUF files under `${MODELS_DIR:-/opt/llamacpp/models}`. The default served IDs are `qwen3coder:30b`, `qwen3.6:35b` and `llama3.1:8b`. The GHCR images may require `docker login ghcr.io` on the host before `docker compose pull` or `docker compose up`.

The services use the official `ghcr.io/ggml-org/llama.cpp:server-cuda` image. They pass `--no-mmap`, `--parallel 1`, `--no-cache-prompt` and reduced batch sizes so model loading and 64k context fit predictably on the production GPUs.

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
