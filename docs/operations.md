# Operations

## Current Inference Layout (production, 2026-11-23)

GPU inference services share the four RTX 3090 and run **one at a time**:

| Service | Compose file | Port | State in production |
| --- | --- | --- | --- |
| `strata-qwen` (Strata 0.2.20, Huihui Qwen3.8-Flash-Next abliterated V2) | `docker-compose.strata-qwen.yml` | `18080` | **Daily service**, preloaded by llama-swap after a reboot (see [strata-qwen.md](strata-qwen.md)) |
| `maya-deepseek` (Project Maya v1.1.65, DeepSeek-V4.1-Flash abliterated) | `docker-compose.maya-deepseek.yml` (own project `octofan-maya`) | `18090` | On demand through llama-swap (see [maya-deepseek.md](maya-deepseek.md)) |
| `llama-swap` (host systemd service) | `llama-swap/config.yaml` | `18100` | Running; starts Strata or Maya by the requested `model` and stops the other (see [model-swap.md](model-swap.md)) |
| `qwen38flash` / `glm53flash` (dedicated llama.cpp) | `docker-compose.qwen38flash.yml` / `docker-compose.glm53flash.yml` | `8091` / `8090` | No containers; kept to reproduce benchmarks |
| `flux` (CPU FLUX.1-schnell) | `docker-compose.flux.yml` (own project `octofan-flux`) | `7860` | Running; uses no GPU |

Ollama was **retired on 2026-11-19**: its service left `docker-compose.yml` and the
container, images and `/opt/ollama` were deleted. The model store is archived on inference2
([ollama-store-archive.md](ollama-store-archive.md)); the recipe to rebuild it stays in
`ollama-custom/README.md`.

Both GPU stacks use `restart: "no"` and belong to llama-swap: do not `up -d` / `stop` them
by hand (see [model-swap.md](model-swap.md)). Deploys of the main stack still name their
services explicitly:

```bash
docker compose up --build -d octofan-controller prometheus node-exporter grafana
```

The controller monitors the inference and image services directly. `strata.endpoints`
lists Strata (`:18080`) and Maya (`:18090`); the backend counts as up when either answers
`/v1/models` (the OLED `ai` profile shows `Strata 1/1 loaded` / `Strata DOWN`, and the
online/warning LEDs follow it). `flux.enabled: true` polls sd-server on `7860` for
`/api/status` and `octofan_flux_up`. `ollama.enabled` and `llamacpp` polling stay `false`.
Both recovery lists name `strata-qwen` and `maya-deepseek`:
`watchdog.gpu_recovery_restart_containers` (GPU-condition failure → `docker restart`) and
`watchdog.ai_recovery_restart_containers` (persistent `/v1/models` failure → `docker
restart`, see the watchdog section below). Only the containers that are running are
restarted, so recovery never starts the stopped backend on top of the active one.

## Start With Hardware

Fresh installation (no dedicated GPU stack running yet):

```bash
docker compose up --build -d
```

Open:

- Controller: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

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

## Compose Orphans Warning

> **Never use `docker compose up --remove-orphans` from the main `docker-compose.yml` while a
> dedicated stack (`docker-compose.strata-qwen.yml`, `docker-compose.qwen38flash.yml`,
> `docker-compose.glm53flash.yml`) is running.** Those containers live in the same Compose
> project namespace (`docker compose ls` shows project `ia-octo-server` with both files) but are
> started from separate compose files, so the main project considers them orphans and
> `--remove-orphans` will stop and remove them. This has happened in production: recreating
> the former `ollama` service with `--remove-orphans` silently deleted the running
> `qwen38flash` container. Today the casualty would be `strata-qwen`. If you need to recreate a
> single service, target it explicitly without that flag
> (`docker compose up -d --force-recreate octofan-controller`), or stop and restart the other
> stacks deliberately if cleanup is actually needed. `flux` and `maya-deepseek` are safe: they
> are their own Compose projects (`octofan-flux`, `octofan-maya`).

## Ollama (retired 2026-11-19)

The Ollama operating notes that used to live here (custom `octofan/ollama:0.35.1-b11381`
image, Modelfile workflow, model inventory, Qwen3.8-Flash-Next vision and uncensored variants,
planned DeepSeek V4 Flash import) are in git history: `git log -S "Ollama On-Demand Models" -- docs/operations.md`
finds the commit that removed them. The Modelfiles stay in `ollama/` and
the image recipe in `ollama-custom/`.

## FLUX Image Generation (CPU)

`docker-compose.flux.yml` runs FLUX.1-schnell (GGUF Q8_0) on the CPUs with
stable-diffusion.cpp `sd-server`. It uses no GPU, so it does not compete with
Strata, Maya or the llama.cpp stacks for VRAM. It is its own Compose project
(`octofan-flux`), so `--remove-orphans` on the main stack does not touch it.

```bash
./scripts/download-flux1-schnell.sh          # ~23 GB into /opt/imagegen/flux
docker compose -f docker-compose.flux.yml up --build -d
```

The image builds from a pinned upstream commit (`SDCPP_REF`). Models stay loaded
in RAM (~23 GB). Web UI at `http://octoserver.core.sied.ar:7860/`. The controller
polls that URL when `flux.enabled: true`; health shows up in `/api/status` as
`flux` and in Prometheus as `octofan_flux_up{source="flux"}` (alert
`OctofanFluxDown`). Flux is not on the OLED and its failure does not blink the
warning LED: it is CPU-only and independent from inference.

OpenAI-compatible API (synchronous, returns base64):

```bash
curl -fsS http://octoserver.core.sied.ar:7860/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"a cozy server room with glowing GPUs, editorial illustration","size":"1344x768","output_format":"jpeg"}' \
  | jq -r '.data[0].b64_json' | base64 -d > cover.jpg
```

Measured 2026-10-23 (2x E5-2680 v4, 28 threads): 1344x768 takes ~8.5 min
(437 s sampling + 61 s VAE decode). Set the client timeout accordingly.

Defaults: 4 steps, cfg 1.0, euler (schnell is distilled). Extra parameters
(seed, steps) go inside the prompt as
`<sd_cpp_extra_args>{"seed":42}</sd_cpp_extra_args>`.

## Front LEDs

The controller can drive the Octofan front LEDs through `fan_controller_cli -l`.

Default mapping:

- LED `0`: orange warning/error.
- LED `1`: blue controller/optional AI health online.
- LED `2`: white GPU activity.

Enable LED control with:

```yaml
leds:
  enabled: true
  poll_interval_seconds: 1.0
  gpu_activity_utilization_percent: 15.0
  gpu_activity_power_watts: 40.0
```

The white activity LED uses NVIDIA utilization or power as an external signal. The controller does not intercept inference requests.

## Watchdog

The code defaults leave the reset policy disabled (`enabled: false`) with
`keepalive_when_disabled: true`, so an Octofan controller with an already-armed firmware watchdog
keeps being fed and does not escalate. The repository `config/octofan.yaml` and production both
**enable** the policy with the configuration below.

To enable host-health watchdog resets:

1. Set `watchdog.enabled: true`.
2. Configure `short_timeout_seconds` and `long_timeout_seconds`.
3. Add one or more checks (`tcp`, `http`, `ssh` or `disk`; `ssh` also validates the `SSH-` banner
   so a zombie sshd that only accepts TCP fails the check; `disk` writes and fsyncs a heartbeat
   file on a host bind mount, see below).
4. Optionally set `gpus_expected` and the GPU recovery keys.

Production configuration:

```yaml
watchdog:
  enabled: true
  keepalive_when_disabled: true
  short_timeout_seconds: 120
  long_timeout_seconds: 1500
  feed_interval_seconds: 30.0
  unhealthy_failures_before_reset: 3
  gpus_expected: 4
  gpu_recovery_enabled: true
  gpu_recovery_grace_seconds: 300
  gpu_recovery_restart_containers:
    - strata-qwen
    - maya-deepseek
  ai_recovery_enabled: true
  ai_recovery_min_failures: 3
  ai_recovery_cooldown_seconds: 900
  ai_recovery_restart_containers:
    - strata-qwen
    - maya-deepseek
  checks:
    - type: ssh
      target: host.docker.internal:22
      timeout_seconds: 1.0
    - type: disk
      target: /watchdog/heartbeat   # host /var/lib/octofan-watchdog, on the root NVMe
      timeout_seconds: 10.0
  host_device: /dev/watchdog      # chipset iTCO (Wellsburg TCO v2), second reset path
  host_timeout_seconds: 180
```

Why both checks: on 2026-11-10 the root NVMe dropped off PCIe (SDES) and the host stayed broken
for ~30 h without a reset, because sshd kept sending its banner from memory. The `disk` check
catches that case: the write+fsync fails with EIO or hangs. A hung write is never retried in
parallel; later cycles fail at once until it returns, so three cycles (~90 s) stop the feed.

If `enabled` is true and any check fails for `unhealthy_failures_before_reset` consecutive watchdog cycles, the daemon does not feed the hardware watchdog. Short transient check failures are tolerated so one missed probe does not trigger a board reset. The frequent `watchdog unhealthy (1/3): ssh:... failed` events seen until 2026-11-15 were false positives: synchronous USB CLI and `nvidia-smi` calls froze the asyncio loop for seconds, so the 1 s banner timeout expired even though sshd answered in ~8 ms. Those calls now run in worker threads; check errors also name the failing step (`connect`/`banner` and the exception type). Failures during the first 120 s after daemon startup are also ignored, which covers bridge-network flaps when containers are recreated. If `enabled` is false and `keepalive_when_disabled` is true, the daemon feeds the hardware watchdog without using it as a reset policy.

With `gpus_expected > 0`, an `nvidia-smi` failure, a GPU count mismatch or phantom entries without UUID mark the watchdog unhealthy. With `gpu_recovery_enabled`, the first failure restarts the containers listed in `gpu_recovery_restart_containers` through the mounted Docker socket and keeps feeding for `gpu_recovery_grace_seconds`; only if the condition persists does the daemon stop feeding. Only listed containers that are running are restarted (a stopped one is skipped, because `docker restart` would start it and take the GPUs from the active backend); the list names both `strata-qwen` and `maya-deepseek` so whichever llama-swap left running is covered.

With `ai_recovery_enabled`, the watchdog also tracks the enabled inference backend (Strata/Maya
through `strata.endpoints` when `strata.enabled`; the legacy Ollama backend when `ollama.enabled`). After
`ai_recovery_min_failures` consecutive 30 s cycles with the backend's health check failing,
the daemon restarts `ai_recovery_restart_containers` and then waits
`ai_recovery_cooldown_seconds` before restarting again (a model reload can take ~10 minutes,
and restarts are suppressed entirely while Docker reports the container as `starting`).
Before 2026-11-15 that suppression never worked: the controller read `State.Health.status`
instead of Docker's `State.Health.Status` and always got `None`. While `ai_recovery_enabled` is
false, failures are no longer banked, so turning it back on does not fire an immediate restart.
Unlike the GPU condition, AI failures never stop the firmware feed: the reset policy stays
reserved for host hangs, and the restart plus the `OctofanStrataDown` Prometheus alert are
the recovery/notification path. Progress is visible in `/api/status` (`ai_recovery`) and as
`octofan_watchdog{metric="ai_recovery_restarts"}`.

`POST /api/watchdog/maintenance` with `{"minutes": N}` (max 240) feeds the firmware regardless of check results. Use it before restarting sshd or disturbing the host network. The state lives in daemon memory and does not survive a controller recreate; the startup grace covers that case.

### Host hardware watchdog (chipset iTCO, since 2026-11-16)

`host_device` makes the daemon open the host's own watchdog (`/dev/watchdog`, driver
`iTCO_wdt`; the controller is privileged so it sees it) with `host_timeout_seconds`, and feed it
exactly when it feeds the Octofan firmware (healthy, startup grace, unhealthy grace, maintenance,
keepalive). When the daemon stops feeding, the chipset resets the host on its own, without the
USB AVR, its firmware or the RESET wire.

Why: on 2026-11-16 the root NVMe dropped twice. At 00:23 PID 1 died with it and kdump rebooted
the host (`/var/crash/127.0.0.1-2026-11-16-00:23:14`). At 00:26 the host stayed alive in RAM with
every exec failing; the daemon could not feed, the firmware was armed (`mode 2`), and it still
took **~3 h** to reset the board (Reset Counter 21 -> 22 at 03:29). The cause of that delay is
inside the firmware and was not identified.

Details:

- Tested 2026-11-16 08:48: with the controller releasing the device and the Octofan still fed,
  opening `/dev/watchdog` and closing it without `V` reset the host after 177 s (timeout 180 s,
  single countdown on this Wellsburg TCO); the Octofan Reset Counter stayed at 22, so the reset
  came from the chipset. The host was back on ssh ~50 s later.
- Feeding is a write on an fd opened once, so it works with the root disk dead.
- If the timeout cannot be set the daemon closes the device and does not arm it: the iTCO default
  (30 s) equals the feed interval and would reset a healthy host.
- A clean stop (compose recreate/stop) writes the magic `V` and disarms it. A crash leaves the
  timer running; the next daemon reopens it within seconds (`restart: unless-stopped`).
- `host_device: null` disables it. State in `/api/status.host_watchdog` and
  `octofan_watchdog{metric="host_armed"|"host_timeout_seconds"}`.
- Do not stop the controller with `docker kill`/SIGKILL for longer than the timeout: without the
  magic close the chipset resets the host.

### Hardware escalation (firmware-level)

The escalation below runs entirely in the Octofan board firmware over its connection to the
motherboard front-panel headers. It works even if the OS is hung, sshd is dead, or the machine
has kernel-panicked: no software on the host participates once the watchdog is armed.

| Timeout | Config key | Board action |
| --- | --- | --- |
| Short | `short_timeout_seconds` | Pulse the motherboard **RESET** header (hardware reset, independent of the OS). |
| Long | `long_timeout_seconds` | The firmware drives **PWR SW**, but this line is disconnected in production. It cannot recover a host that remains stuck after RESET. |

Current production values: short `120s`, long `1500s`. With `feed_interval_seconds: 30` and
`unhealthy_failures_before_reset: 3`, a hung host (SSH check failing) stops being fed after
~90-120s. If the Octofan remains powered and armed, the short timeout pulses RESET. The long
timeout cannot power-cycle this production host; use the smart plug to cut AC power if RESET
does not recover it. See [the current wiring and power-cycle procedure](watchdog-power-cycle.md).

Limits:

- The board cannot cut mains power. Production uses a SmartLife/Tuya smart plug for AC
  power cycling, with power recovery set to ON.
- The watchdog state lives in the board. If the controller container dies while the watchdog is
  armed, the board escalates on its own. Use `keepalive_when_disabled: true` when intentionally
  disabling the reset policy so a stopped/unhealthy controller does not trip the board.
- The `octofan-poc-safety.service` systemd unit (legacy llama.cpp RPC POC loop) is disabled and
  must stay disabled: two feeders on the same USB device race and mask real watchdog events.

Inspect the live board state (armed mode and cumulative reset counter) with:

```bash
docker exec octofan-controller /opt/octofan/fan_controller_cli -h | grep -i watch
# Watch-Dog Mode: 2    Reset Counter = 19
```

`Watch-Dog Mode` is `0` when disarmed and non-zero when armed. `Reset Counter` is cumulative in
firmware and includes resets from the HiveOS era of this board.

## Fan Control

Auto mode calculates independent demand from intake, exhaust, their positive temperature delta
and the hottest NVIDIA GPU, then uses the highest demand. Production uses these curves:

| Signal | Quiet minimum | Curve maximum | Immediate critical |
| --- | ---: | ---: | ---: |
| Intake | <=30C at 10% | 40C at 100% | 45C |
| Exhaust | <=30C at 10% | 45C at 100% | 50C |
| Exhaust - intake | <=7C at 10% | 18C at 100% | 22C |
| Hottest GPU | <=45C at 10% | 70C at 85% | 88C |

Between each pair of points, demand is interpolated linearly. Intake, exhaust and delta can request
the full configured range. The GPU curve starts early because the middle GPU reached 80C and 95%
onboard fan speed while the chassis target was only 34%. At 55C, 60C and 65C the GPU requests
40%, 55% and 70% chassis fan speed respectively. The 85% cap applies from 70C to the critical
threshold of 88C, which immediately requests 100%. Normal increases are limited by
`max_step_percent` per poll;
decreases use the slower `max_down_step_percent`. Changes within `target_deadband_percent` are
ignored. Crossing any critical threshold immediately selects `max_percent` without slew limiting.

Intake prefers BME280 No. 0 and exhaust prefers BME280 No. 1 or `Temperature No. 1`, with sane
fallbacks. Temperatures below `-20C` or above `120C` are ignored. If the controller cannot be read
or no thermal signal remains, fans ramp toward `fail_safe_percent`; setting `fail_safe_ramp: false`
makes that transition immediate. GPU telemetry failure does not force full speed while valid
intake/exhaust sensors remain available.

The API exposes the complete decision as `fan_control`. Prometheus exports pre-slew demands as
`octofan_fan_control_target_percent{source="intake|exhaust|delta|gpu|combined"}`, shown in the Cooling
dashboard's `Automatic Policy Demand` panel.

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

The controller only enters idle mode when `nvidia-smi` is healthy, all GPUs are below the configured utilization, power and temperature thresholds, no monitored AI backend (llama.cpp or Ollama) is generating, no GPU has encoder/decoder sessions, and intake temperature is below the configured limit. Manual and automatic targets are clamped to `min_percent..max_percent`, so requests below the known active range do not produce misleading PWM targets. Any load, hotter temperature, missing GPU reading or controller read failure returns to the normal fan curve or fail-safe behavior.

## OLED Display

The dynamic display refresh is controlled in `config/octofan.yaml`:

```yaml
display:
  refresh_interval_seconds: 15.0
  persist_to_eeprom: true
```

When `persist_to_eeprom` is true, the controller writes the static OLED layout to EEPROM once per process start/profile change, and whenever `POST /api/display/render` is called. Runtime values continue to refresh at the normal interval without rewriting EEPROM every cycle.

The `ai` profile prints the host IP on its first line. The controller resolves it from the host
hostname and `/etc/hosts` (both mounted read-only from the host); set `OCTOFAN_DISPLAY_IP` in `.env`
to override the detected address.

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

The controller and the GPU inference stacks request `gpus: all`: the controller uses it for `nvidia-smi`, while Strata and Maya split the model across every installed GPU without a maintained index list. The controller also mounts `/var/run/docker.sock` so the watchdog GPU recovery can restart containers, and `/etc/hostname` plus `/etc/hosts` read-only for the OLED title and IP line.

`node-exporter` runs in the host network namespace. Without this, Linux network metrics would show the exporter container interface instead of the host NIC.

Keep the controller UI/API on a trusted LAN. v1 has no authentication.
