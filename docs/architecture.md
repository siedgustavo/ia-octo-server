# Architecture

Octofan AI Server is a small container stack around the original Octominer USB controller.

## Components

- `octofan-controller`: Python/FastAPI daemon. It owns hardware reads, fan decisions, OLED rendering, watchdog feeding and Prometheus metrics.
- `nvidia-smi`: queried by the controller container for GPU telemetry when NVIDIA Container Toolkit is available.
- `fan_controller_cli`: original Octominer binary copied into the controller image from `reference/octofan-hiveos-originals/`.
- `prometheus`: scrapes `octofan-controller:8000/metrics`.
- `node-exporter`: exposes host CPU, memory, disk, filesystem and network metrics. It runs with `network_mode: host` so network counters come from the host namespace instead of the exporter container.
- `grafana`: loads the Prometheus datasource and the Octofan dashboard set.
- `ollama`: on-demand model server with both NVIDIA GPUs visible and persistent model storage under `/opt/ollama`.
- `comfyui`: FLUX.1-dev FP8 image generation on GPU 3. It is exposed for direct UI/API use and is not currently polled by the controller.

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
10. The LED loop maps controller health and NVIDIA activity to front-panel LEDs through `fan_controller_cli -l`.
11. The watchdog loop runs configured checks and feeds the watchdog with `fan_controller_cli -s` only when healthy.

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

The compose stack uses the Docker network `octofan-ai` by default. Ollama is reachable within the network at `http://ollama:11434` and ComfyUI at `http://comfyui:8188`; the controller does not depend on either service.
