# API and Metrics

## REST API

### `GET /api/status`

Returns current controller status, fan data, PSU data, BME280 readings, watchdog result, Ollama status and recent events.

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

Renders and writes a display profile.

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

Thermal:

- `octofan_temperature_celsius{source,id}`
- `octofan_bme_humidity_percent{id}`
- `octofan_bme_pressure_hpa{id}`

Fans:

- `octofan_fan_rpm{id}`
- `octofan_fan_percent{id}`
- `octofan_fan_pwm{id}`

Power:

- `octofan_power_ac_total_watts`
- `octofan_psu_metric{id,model,metric}`

Watchdog:

- `octofan_watchdog{metric}`

AI:

- `octofan_ai_tokens_per_second{source="ollama"}`
- `octofan_ai_running_models{source="ollama"}`

## Notes

Ollama `/api/ps` does not expose complete live token accounting. The current v1 surface detects active/running models and keeps a stable metric/API shape for richer instrumentation later.
