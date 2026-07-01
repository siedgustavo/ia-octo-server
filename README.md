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
- Updates the controller OLED with host, thermal, power and RPC backend status.
- Drives the front-panel LEDs for RPC health and GPU activity.
- Feeds the hardware watchdog only when configured host checks pass.
- Runs GPU-pinned llama.cpp RPC backend containers over Docker networking.

## Services

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage.
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).
- `llamacpp-rpc-gpu*`: llama.cpp RPC GPU backends at `5000` through `5003`.

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
- `rpc`: TCP health checks for the llama.cpp RPC backend containers.

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

## llama.cpp RPC

This stack runs only the GPU bridge side on `octoserver.core.sied.ar` (`172.16.1.39`). It does not load GGUF models and does not expose OpenAI-compatible model APIs.

The model host/client lives on `aiworker.core.sied.ar` (`172.16.1.40`) and connects to these RPC endpoints:

```text
octoserver.core.sied.ar:5000 -> GPU 0
octoserver.core.sied.ar:5001 -> GPU 1
octoserver.core.sied.ar:5002 -> GPU 2
octoserver.core.sied.ar:5003 -> GPU 3
```

Enable `rpc.enabled` in `config/octofan.yaml` to let the controller check that the four RPC ports are reachable. The controller does not query `/v1/models`, tokens, loaded model names or model throughput.

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

RPC container GPU and port mapping are configurable through environment variables:

```env
LLAMACPP_RPC_IMAGE=evilfreelancer/llama.cpp-rpc:latest-cuda
LLAMACPP_RPC_GPU0_DEVICE=0
LLAMACPP_RPC_GPU0_PORT=5000
```

Each RPC service runs `/app/rpc-server` directly, bypassing the image entrypoint, and reserves one NVIDIA device with Docker Compose `device_ids`. NVIDIA Container Toolkit must be available on the host.

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
