![Octoserver: an Octominer repurposed for local AI inference with four RTX 3090 GPUs](docs/images/octoserver-cover.png)

# Octoserver · From mining rig to local AI

**Four RTX 3090s. 96 GiB of VRAM. A second life for an Octominer.**

[![GPUs](https://img.shields.io/badge/GPU-4%C3%97_RTX_3090-76B900)](#the-hardware)
[![VRAM](https://img.shields.io/badge/VRAM-96_GiB-0078D4)](#the-hardware)
[![Inference](https://img.shields.io/badge/Inference-Strata_%2B_Maya-blue)](#services)
[![Monitoring](https://img.shields.io/badge/Monitoring-Prometheus_%2B_Grafana-orange)](#what-it-does)

A mining chassis gets a new job: running large language models locally, with its
own cooling control, hardware watchdog, live dashboards and an OLED status display.
**The GPUs do the inference. The rest of the stack keeps the machine running.**

This repository contains the Octofan AI Server stack, hardware notes and performance
experiments behind Octoserver. Including the experiments that proved our first
explanation wrong.

**[Explore the benchmarks](#measured-not-just-built)** ·
**[Get started](#quick-start)** ·
**[Read the architecture](docs/architecture.md)** ·
**[Browse the docs](#documentation)**

## Measured, not just built

Results recorded through November 23, 2026, with all four GPU links at PCIe Gen3
x8:

| Workload | Result | What it means |
|---|---:|---|
| gpt-oss-120b MXFP4, Ollama, ~2k prompt | **104 tokens/s** generation | A 120B-class model running entirely on the GPUs (Ollama was retired on 2026-11-19) |
| Huihui Qwen3.8-Flash-Next abliterated V2, Strata 0.2.20, ~114k prompt | **4732 tokens/s** prompt · **115 tokens/s** generation | The current daily inference service since 2026-11-23 (MTP speculative decoding + expert cache, GPUs capped at 250 W); 147–165 tokens/s on short prompts |
| Same model, Strata 0.2.7, ~6.8k prompt | **1286 tokens/s** prompt · **96–128 tokens/s** generation | The October 31 baseline; median 101 tokens/s over 24 h of real mixed use |
| Qwen3.8-Flash-Next, llama.cpp b11381, ~4k prompt | **634 tokens/s** prompt · **58 tokens/s** generation | The former dedicated llama.cpp service, later served through custom Ollama; long-context decode improves more |
| GLM-5.3-Flash IQ1_S, auto-fit, ~4k prompt | **227 tokens/s** prompt · **21.5 tokens/s** generation | A larger MoE model using GPU memory plus CPU offload |

The Strata figures come from a configuration comparison, not an engine shootout
with identical optimizations: see [Strata notes](docs/strata-qwen.md).

### How does it compare with a DGX Spark?

Our gpt-oss-120b run recorded **104 tokens/s**, versus **58.7 tokens/s** in the
published llama.cpp DGX Spark reference: an observed **1.8× difference**.

That's a compelling result for repurposed hardware, but **not a controlled
hardware shootout**: our run used Ollama and its GGUF conversion; the Spark
reference used llama-bench, a different build and different context handling.
These measurements do not establish a universal speed advantage. Nor do they
establish a tokens-per-watt winner: our power samples were not synchronized with
a matching Spark measurement.

**[Read the comparison, measurements and limitations →](docs/octoserver-vs-dgx-spark.md)**

### The tuning lessons were just as useful

- **New risers helped, but tensor split still lost.** Layer split delivered
  2.26× the prompt throughput and 2.54× the generation throughput of the tested
  tensor configuration. [Results →](docs/qwen38flash-split-benchmark.md)
- **More GPUs only help if their memory gets used.** One manual GLM placement
  left GPU 0 and GPU 1 almost empty. Auto-fit made substantially better use of
  the available VRAM. [Results →](docs/glm53flash-benchmark.md)
- **Capacity and speed are different constraints.** A model fitting entirely
  on the GPUs behaves very differently from one that needs CPU offload.

## The hardware

| Component | Octoserver |
|---|---|
| Chassis | Repurposed Octominer / Octofan mining enclosure |
| GPUs | **4 × NVIDIA RTX 3090**, 24 GiB each, Ampere |
| GPU links | PCIe Gen3 x8 per card, direct CPU root ports |
| GPU peer-to-peer | Unavailable in the measured configuration |
| CPU | 2 × Intel Xeon E5-2680 v4, 28 cores / 56 threads total |
| Host memory | Approximately 125 GiB reported by the OS |
| Storage | Samsung 980 PRO 2 TB NVMe |
| Deployment | Docker Compose; Strata (daily) and Maya (on demand) swapped by llama-swap, plus dedicated llama.cpp benchmark stacks |

The 96 GiB of VRAM is distributed across four cards, not a single unified memory
pool. Model placement, KV cache and temporary buffers all matter.

## More than a model server

The stack keeps the original `fan_controller_cli` binary as the hardware interface
and replaces the HiveOS scripts with a Python/FastAPI controller, Prometheus
metrics and provisioned Grafana dashboards. It connects inference software to the
physical machine: temperatures, power supplies, fans, LEDs and watchdog recovery.

The original HiveOS package files are preserved as reference material under
`reference/octofan-hiveos-originals/`.

## What It Does

- Reads Octofan controller telemetry through the original USB CLI.
- Controls chassis fans from internal case temperature.
- Exposes all controller telemetry as Prometheus metrics.
- Adds NVIDIA GPU telemetry from `nvidia-smi`.
- Adds host CPU, memory, disk and network telemetry through node exporter.
- Ships Grafana dashboards for overview, PSUs, environment, cooling, GPUs and host/network, plus Prometheus alert rules for GPU inventory, frozen GPU readings, GPU temperature and controller availability.
- Updates the controller OLED with host, thermal, power and AI status.
- Drives the front-panel LEDs from controller health and GPU activity.
- Feeds the hardware watchdog only when configured host checks (TCP, HTTP, SSH banner or a disk write+fsync heartbeat) and the GPU inventory condition pass; the firmware pulses the motherboard RESET line when feeding stops.
- Serves LLM inference on all four GPUs: Strata (Qwen) for daily use and Maya (DeepSeek) on demand, one at a time, swapped by llama-swap.

## Services

Main `docker-compose.yml`:

- `octofan-controller`: FastAPI daemon, UI, REST API, Prometheus exporter, fan control, watchdog and OLED updates.
- `prometheus`: metrics storage and alert rules (`prometheus/rules/`).
- `node-exporter`: host system and network metrics, running in the host network namespace.
- `grafana`: dashboard at `http://localhost:3000` (`admin` / `octofan`).

Dedicated Compose files (same Compose project, started with `-f`; see the
`--remove-orphans` warning in `docs/operations.md`):

- `strata-qwen`: Strata 0.2.20 serving Huihui Qwen3.8-Flash-Next abliterated V2 on port `18080` (OpenAI-compatible, no API key), defined in `docker-compose.strata-qwen.yml`. **The daily inference service since 2026-10-31**, and the model llama-swap preloads after a reboot. The controller polls its `/v1/models` for OLED/LED/status health and restarts the container when it stops answering. See `docs/strata-qwen.md`.
- `maya-deepseek`: Project Maya serving DeepSeek-V4.1-Flash abliterated (Mix-128G, 1M context, vision) on port `18090`, defined in `docker-compose.maya-deepseek.yml` (own Compose project `octofan-maya`). Started on demand. See `docs/maya-deepseek.md`.
- `llama-swap` (host systemd service, port `18100`, config `llama-swap/config.yaml`): starts Strata or Maya according to the requested `model` and stops the other. Only OpenCode goes through it; never start or stop those two stacks by hand. See `docs/model-swap.md`.
- `qwen38flash`: dedicated llama.cpp service on port `8091`, defined in `docker-compose.qwen38flash.yml`. Not deployed at the moment; kept to reproduce benchmarks.
- `glm53flash`: dedicated llama.cpp service on port `8090`, defined in `docker-compose.glm53flash.yml`. Not deployed at the moment; kept to reproduce benchmarks.
- `flux`: CPU-only FLUX.1-schnell image generation (stable-diffusion.cpp `sd-server`) on port `7860`, defined in `docker-compose.flux.yml` as its own Compose project (`octofan-flux`). Health-polled by the controller (`octofan_flux_up`). See `docs/operations.md`.

The GPU inference services compete for the same GPU memory and must run one at
a time. The benchmarks above ran them individually.

## Repository Layout

- `controller/`: Python FastAPI controller service.
- `config/octofan.yaml`: mounted runtime configuration.
- `grafana/`: provisioned datasource and dashboards.
- `prometheus/`: scrape configuration and alert rules.
- `reference/octofan-hiveos-originals/`: original HiveOS files retained for reference.
- `tests/`: parser, control, display, watchdog, compose and API tests.
- `llamacpp/`: dedicated llama.cpp images and KV-cache persistence entrypoint.
- `ollama/`, `ollama-custom/`: Modelfiles, Dockerfile and patches of the retired Ollama service, kept as a recipe (`ollama-custom/README.md`).
- `maya/`: Maya engine configuration.
- `llama-swap/`: llama-swap configuration for the Strata/Maya swap.
- `strata/`: Strata engine configuration.
- `scripts/`: model download helpers.
- `host/`: host-level sysctl tuning.
- `docs/`: benchmarks, hardware investigations and operating notes.
- `tools/expert-profiler/`: MoE expert profiling experiments.

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
- `watchdog`: hardware watchdog timeouts, TCP/HTTP/SSH health checks, expected GPU count and container recovery before the firmware escalates.
- `display`: OLED profile and refresh interval.
- `leds`: front-panel LED policy. By default LED `0` is orange warning, LED `1` is blue online and LED `2` is white activity.
- `llamacpp`: optional legacy health polling; disabled in production.
- `ollama`: legacy health polling for the retired Ollama service (`enabled`, `base_url`, `timeout_seconds`); `enabled: false` in production.
- `strata`: inference health polling for the daily service (`enabled`, `base_url`, `endpoints`, `timeout_seconds`). `endpoints` lists Strata (`:18080`) and Maya (`:18090`): the backend is up when either answers `/v1/models`. It is reflected in `/api/status`, the OLED `ai` profile and the online/warning LEDs, and the watchdog's AI recovery restarts whichever of `strata-qwen` / `maya-deepseek` is running on persistent failure.
- `flux`: image-generation health polling (`enabled`, `base_url` → `http://host.docker.internal:7860`, `timeout_seconds`). Reported in `/api/status` and `octofan_flux_up` only.

Automatic fan control combines BME280 intake, exhaust, exhaust-minus-intake delta and a capped
hottest-GPU assistance curve, then applies the highest demand. Chassis temperatures govern normal
airflow; GPU temperature only contributes above 75C and cannot request more than 40% before the
88C emergency threshold. Invalid sensors are filtered independently, while critical temperatures
override normal slew limits. The API, Prometheus and Cooling dashboard expose each signal's demand.

`fans.gpu_idle_stop_enabled` can hold the chassis fans at the lowest active configured speed while NVIDIA GPUs are idle and cool. Manual and automatic targets are clamped to `fans.min_percent..fans.max_percent`, and the idle policy falls back to the normal auto curve when GPU load, GPU temperature, intake temperature or telemetry health no longer matches the configured idle thresholds.

The OLED `ai` profile shows the host IP, AI health (`Strata N/N loaded`, `Strata DOWN`, `Ollama N loaded`, `Ollama DOWN`, `AI services OK` or `AI monitor off`, preferring Strata, then Ollama, then llama.cpp), hottest-GPU temperature and load, intake temperature with the current fan percent, and total power. The host IP is auto-detected from the host hostname and `/etc/hosts` (both mounted read-only into the controller); set `OCTOFAN_DISPLAY_IP` in `.env` to pin a specific address.

## API

- `GET /api/status`
- `GET /api/config`
- `PUT /api/config`
- `POST /api/fans/manual`
- `POST /api/fans/auto`
- `POST /api/display/render`
- `POST /api/watchdog/test`
- `POST /api/watchdog/maintenance`
- `POST /api/calibrate-fans`
- `GET /metrics`

## Ollama (retired)

Ollama was removed from octoserver on 2026-11-19: the `ollama` service left
`docker-compose.yml` and its container, images and `/opt/ollama` were deleted.
Strata replaced it as the daily service on 2026-10-31, and Maya covers DeepSeek.

- The model store is archived cold on inference2: see
  [Ollama store archive](docs/ollama-store-archive.md) for tags, verification and restore.
- `ollama-custom/` (Dockerfile + patches) and the Modelfiles in `ollama/` stay as a recipe;
  `ollama-custom/README.md` explains how to bring the service back from git history
  (`git log -S "octofan-ollama" -- docker-compose.yml`).
- Never run it next to Strata or Maya: they all need the four GPUs.

Other cold archives: GLM-5.3 models ([GLM models archive](docs/glm-models-archive.md)) and the
legacy llama.cpp coder models ([llama.cpp models archive](docs/llamacpp-models-archive.md)).

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
- [Strata daily inference service](docs/strata-qwen.md)
- [GLM-5.3-Flash tuning and lessons](docs/glm53flash-benchmark.md)
- [Qwen3.8-Flash-Next split benchmark](docs/qwen38flash-split-benchmark.md)
- [Octoserver vs NVIDIA DGX Spark](docs/octoserver-vs-dgx-spark.md)
- [KV-cache persistence for the dedicated llama.cpp stacks](docs/kv-cache-persistence.md)
- [GLM-5.3-Flash expert affinity](docs/glm53flash-expert-affinity.md) and [ktransformers POC](docs/glm53flash-ktransformers-poc.md)
- [Hardware mods](docs/hardware-mods.md)
- [Watchdog and power-cycle decisions](docs/watchdog-power-cycle.md)
