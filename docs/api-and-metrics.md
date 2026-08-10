# API and Metrics

## REST API

### `GET /api/status`

Returns current controller status, fan data, PSU data, BME280 readings, watchdog result, llama.cpp
status, recent events and `fan_control`, including applied/raw targets, the controlling reason and
the intake, exhaust and GPU demands.

When GPU idle stop is enabled, the response also includes `gpu_idle_seconds` and `gpu_idle_stop_active`.

The response also includes current LED control state under `leds`.

### `GET /api/config`

Returns the active YAML configuration as JSON.

### `PUT /api/config`

Replaces the active configuration. The payload must match the config schema used by `config/octofan.yaml`.

### `POST /api/fans/manual`

Sets manual fan mode.

Payload:

```json
{"percent": 70}
```

### `POST /api/fans/auto`

Switches fans back to automatic mode.

### `POST /api/display/render`

Renders and writes a display profile. When `display.persist_to_eeprom` is enabled, this also rewrites the static OLED layout in controller EEPROM.

Payload:

```json
{"profile": "ai"}
```

Supported profiles are `system`, `thermal`, `power` and `ai`.

### `POST /api/watchdog/test`

Runs the configured watchdog checks without changing watchdog state.

### `POST /api/calibrate-fans`

Saves current fan RPM as max RPM through the controller CLI. Use this only when fans are intentionally running at calibration speed.

### `GET /metrics`

Prometheus scrape endpoint.

## Metrics

Core:

- `octofan_controller_up`
- `octofan_controller_version{type="cli|fw|hw|boot"}`
- `octofan_target_fan_percent`
- `octofan_fan_control_target_percent{source="intake|exhaust|delta|gpu|combined"}`
- `octofan_voltage_volts{id}`

Thermal:

- `octofan_temperature_celsius{source,id}`
- `octofan_intake_temperature_celsius`
- `octofan_exhaust_temperature_celsius`
- `octofan_temperature_delta_celsius`
- `octofan_bme_humidity_percent{id}`
- `octofan_bme_pressure_hpa{id}`

Fans:

- `octofan_fan_rpm{id}`
- `octofan_fan_percent{id}`
- `octofan_fan_pwm{id}`

Power:

- `octofan_power_ac_total_watts`
- `octofan_psu_metric{id,model,metric}`

Common PSU metric values include `voltage_ac`, `amperage_ac`, `power_ac`, `voltage_dc`, `amperage_dc`, `power_dc`, `temp_1`, `temp_2`, `temp_3`, `fan_rpm`, `peak_power_ac`, `peak_amperage_dc` and `energy_ac_kwh`.

Watchdog:

- `octofan_watchdog{metric}`

NVIDIA:

- `octofan_nvidia_smi_up`
- `octofan_nvidia_gpu_info{index,uuid,name,pci_bus_id,driver_version,vbios_version}`
- `octofan_nvidia_gpu_metric{index,uuid,name,metric}`

Common NVIDIA metric values include `temperature_gpu_c`, `temperature_memory_c`, `fan_speed_percent`, `utilization_gpu_percent`, `utilization_memory_percent`, `memory_total_mib`, `memory_used_mib`, `memory_free_mib`, `power_draw_watts`, `power_limit_watts`, `clock_graphics_mhz`, `clock_memory_mhz`, `pcie_link_gen_current`, `pcie_link_width_current`, `encoder_sessions` and `decoder_sessions`.

AI:

- `octofan_ai_tokens_per_second{source="llamacpp"}`
- `octofan_ai_tokens_per_second_available{source="llamacpp"}`
- `octofan_ai_available_models{source="llamacpp"}`
- `octofan_ai_running_models{source="llamacpp"}`
- `octofan_llamacpp_up{name,gpu,model}`
- `octofan_llamacpp_slots{name,gpu,state="total|processing"}`

Host and network:

The stack includes `node_exporter`, scraped by Prometheus as `node-exporter:9100`. It provides standard `node_*` metrics for CPU, memory, filesystems, disks and network interfaces.

## Dashboards

Grafana provisions these dashboards under the `Octofan` folder:

- `Octofan - Overview`: operating view for controller health, thermal envelope, power, fans, GPU load, host CPU/memory and AI throughput.
- `Octofan - Power Supplies`: AC/DC rails, watts, current, PSU temperatures, PSU fan RPM, peaks and accumulated AC energy.
- `Octofan - Environment`: selected sane intake/exhaust temperatures, raw sensor channels, BME280 humidity/pressure and controller voltage inputs.
- `Octofan - Cooling`: chassis fan RPM, PWM, target percent, PSU fans and cooling result versus heat sources.
- `Octofan - GPUs`: NVIDIA SMI status, GPU temperature, power, utilization, VRAM, clocks, PCIe and encoder sessions.
- `Octofan - Host and Network`: node exporter CPU, memory, filesystems, disk I/O and network throughput.

## Notes

llama.cpp health is read from `/health`, model properties from `/props`, and active generation from `/slots`. The controller does not derive live token counters from those polling APIs, so `octofan_ai_tokens_per_second_available{source="llamacpp"}` remains `0` unless the application that calls inference exports request-level token telemetry separately.
