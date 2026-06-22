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
- Drives the front-panel LEDs for AI runtime health and GPU activity.
- Feeds the hardware watchdog only when configured host checks pass.
- Integrates with a vLLM OpenAI-compatible server over Docker networking.

## Services

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage.
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).
- `vllm`: vLLM OpenAI-compatible inference API at `http://localhost:8001/v1`.

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
- vLLM: `http://localhost:8001/v1`

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
OCTOFAN_MOCK=1 OCTOFAN_CONTROLLER_PORT=18000 PROMETHEUS_PORT=19090 GRAFANA_PORT=13000 VLLM_PORT=18001 docker compose up --build
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
- `ai`: external AI runtime endpoint.

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

## vLLM

Enable `ai.enabled` in `config/octofan.yaml` and point `ai.base_url` to the vLLM endpoint. The OLED and Grafana dashboard include model inventory from `/v1/models`, running/waiting request state from vLLM metrics, and token throughput calculated from vLLM Prometheus counters.

The compose stack includes a `vllm` service on the same Docker network. Enable controller-side polling with:

```yaml
ai:
  enabled: true
  provider: vllm
  base_url: http://vllm:8000
  timeout_seconds: 5.0
```

The compose stack creates/uses the `octofan-ai` network by default. If vLLM is managed by another compose project instead, attach that container to the network and set `ai.base_url` accordingly.

The vLLM service uses `gpus: all`, so NVIDIA Container Toolkit must be available on the host. It also uses `ipc: host`, as recommended by vLLM for PyTorch shared memory.

The default model is `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8`, served as `qwen3-coder:30b` for client compatibility. Override it before startup with `VLLM_MODEL`, `VLLM_SERVED_MODEL_NAME`, `VLLM_TENSOR_PARALLEL_SIZE`, `VLLM_MAX_MODEL_LEN`, `VLLM_GPU_MEMORY_UTILIZATION`, `VLLM_NVIDIA_VISIBLE_DEVICES` and `HF_TOKEN` when the model requires Hugging Face authentication.

Legacy `ollama:` config is still accepted and migrated in memory as provider `ollama`, but new config should use `ai:`.

When migrating an existing deployment, use `docker compose up --build -d --remove-orphans` once so the old `octofan-ollama` container does not keep GPUs allocated.

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
