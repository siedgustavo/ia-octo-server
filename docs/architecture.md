# Architecture

Octofan AI Server is a small container stack around the original Octominer USB controller.

## Components

Main `docker-compose.yml`:

- `octofan-controller`: Python/FastAPI daemon. It owns hardware reads, fan decisions, OLED rendering, LED control, watchdog feeding (including the GPU inventory condition and container recovery through the mounted Docker socket) and Prometheus metrics.
- `nvidia-smi`: queried by the controller container for GPU telemetry when NVIDIA Container Toolkit is available.
- `fan_controller_cli`: original Octominer binary copied into the controller image from `reference/octofan-hiveos-originals/`.
- `prometheus`: scrapes `octofan-controller:8000/metrics` and the node exporter at `host.docker.internal:9100`; evaluates the alert rules in `prometheus/rules/`.
- `node-exporter`: exposes host CPU, memory, disk, filesystem and network metrics. It runs with `network_mode: host` so network counters come from the host namespace instead of the exporter container.
- `grafana`: loads the Prometheus datasource and the Octofan dashboard set.
- `ollama`: model server built from `ollama-custom/Dockerfile` with every host NVIDIA GPU visible and persistent model storage under `/opt/ollama`. In production it is currently stopped as a fallback while Strata owns the GPUs. It lives behind the Compose profile `ollama`, so a bare `docker compose up -d` never starts it.

Dedicated Compose files (same project namespace, started with `-f`):

- `strata-qwen` (`docker-compose.strata-qwen.yml`): Strata engine serving the daily Qwen model on port 18080 with an OpenAI-compatible API. Its config lives in `strata/strata-qwen.json`.
- `qwen38flash` / `glm53flash` (`docker-compose.qwen38flash.yml`, `docker-compose.glm53flash.yml`): dedicated llama.cpp servers with disk-persisted KV slots, used for the benchmarks in `docs/`. Not deployed at the moment.
- `flux` (`docker-compose.flux.yml`, own project `octofan-flux`): CPU-only image generation; independent of the GPU services.

The controller polls llama.cpp (`llamacpp.servers`), Ollama (`ollama.base_url`), Strata (`strata.base_url`, via the OpenAI-compatible `/v1/models`) and Flux (`flux.base_url`). The OLED/LED AI health line follows the first enabled backend in the order Strata → Ollama → llama.cpp; Flux is reported only through `/api/status` and `octofan_flux_up`. While an enabled inference backend fails its health check, the watchdog's AI recovery restarts the containers in `watchdog.ai_recovery_restart_containers` (suppressing restarts while Docker health reports `starting`, i.e. model load) and restarts are rate-limited by `ai_recovery_cooldown_seconds`; unlike the GPU condition, AI failures never stop the firmware feed.

## Data Flow

1. The controller polls `fan_controller_cli -r`.
2. Raw CLI text is parsed into structured controller status.
3. The control loop calculates a target chassis fan percentage.
4. Fan targets are applied with `fan_controller_cli -f <fan> -v <pwm>`.
5. Metrics are exported at `/metrics`.
6. NVIDIA GPU telemetry is read from `nvidia-smi` and exported with the controller metrics.
7. Prometheus scrapes the controller and node exporter metrics.
8. Grafana visualizes overview, PSU, environment, cooling, GPU and host/network dashboards.
9. The OLED loop renders an 8-line, 20-character layout through `fan_controller_cli -o`.
10. The LED loop maps controller health, AI backend health and NVIDIA activity to front-panel LEDs through `fan_controller_cli -l`.
11. The watchdog loop arms the firmware watchdog with `fan_controller_cli -w <short> -v <long>`, runs the configured checks plus the GPU inventory condition, and feeds it with `fan_controller_cli -s` only while healthy (or during startup grace, maintenance mode or a GPU recovery window). When feeding stops, the firmware pulses the motherboard RESET line after the short timeout (see `watchdog-power-cycle.md`).

## Hardware Interface

The controller image runs privileged and mounts `/dev/bus/usb` because `fan_controller_cli` uses libusb. The v1 design intentionally does not reimplement the USB protocol.

Supported controller surfaces include:

- firmware, hardware and bootloader version
- serial number
- BME280 temperature, humidity and pressure
- simple temperature and voltage channels
- fan RPM, max RPM, current PWM and percent
- PSU AC/DC power, voltage, current, temperature, fan, peak and accumulated energy values
- watchdog mode, timeouts and reset counter
- OLED text
- LEDs

## Network Model

The compose stack uses the Docker network `octofan-ai` by default. Ollama is reachable within the network at `http://ollama:11434`; the controller does not depend on the inference service for hardware watchdog health. `strata-qwen` uses its own network (`strata-qwen`) and publishes port 18080 on the host; `flux` publishes 7860. The controller monitors both through `host.docker.internal` (`strata.base_url` / `flux.base_url`). The controller reaches the host sshd for the watchdog check, and Prometheus reaches the node exporter, through `host.docker.internal` (`extra_hosts: host-gateway`).
