from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class FanConfig(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    min_percent: int = Field(default=35, ge=1, le=100)
    max_percent: int = Field(default=100, ge=1, le=100)
    manual_percent: int = Field(default=70, ge=1, le=100)
    max_step_percent: int = Field(default=8, ge=1, le=100)
    max_down_step_percent: int = Field(default=4, ge=1, le=100)
    target_deadband_percent: int = Field(default=2, ge=0, le=20)
    critical_confirm_samples: int = Field(default=2, ge=1, le=10)
    intake_ramp_start_c: float = Field(default=30.0, ge=-20.0, le=120.0)
    intake_full_speed_c: float = Field(default=40.0, ge=-20.0, le=120.0)
    intake_critical_c: float = Field(default=45.0, ge=-20.0, le=120.0)
    exhaust_ramp_start_c: float = Field(default=30.0, ge=-20.0, le=120.0)
    exhaust_full_speed_c: float = Field(default=45.0, ge=-20.0, le=120.0)
    exhaust_critical_c: float = Field(default=50.0, ge=-20.0, le=120.0)
    delta_ramp_start_c: float = Field(default=7.0, ge=0.0, le=120.0)
    delta_full_speed_c: float = Field(default=18.0, ge=0.0, le=120.0)
    delta_critical_c: float = Field(default=22.0, ge=0.0, le=120.0)
    gpu_ramp_start_c: float = Field(default=75.0, ge=0.0, le=120.0)
    gpu_full_speed_c: float = Field(default=85.0, ge=0.0, le=120.0)
    gpu_critical_c: float = Field(default=88.0, ge=0.0, le=120.0)
    gpu_curve_max_percent: int = Field(default=40, ge=1, le=100)
    ai_load_assist: bool = True
    ai_load_boost_percent: int = Field(default=10, ge=0, le=50)
    fail_safe_percent: int = Field(default=100, ge=1, le=100)
    fail_safe_ramp: bool = True
    poll_interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    gpu_idle_stop_enabled: bool = False
    gpu_idle_stop_percent: int = Field(default=0, ge=0, le=100)
    gpu_idle_stop_delay_seconds: float = Field(default=300.0, ge=0.0, le=3600.0)
    gpu_idle_utilization_percent: float = Field(default=5.0, ge=0.0, le=100.0)
    gpu_idle_power_watts: float = Field(default=25.0, ge=0.0, le=1000.0)
    gpu_idle_max_gpu_temp_c: float = Field(default=45.0, ge=0.0, le=120.0)
    gpu_idle_max_intake_temp_c: float = Field(default=35.0, ge=0.0, le=120.0)

    @model_validator(mode="after")
    def validate_thermal_curves(self) -> "FanConfig":
        for source in ("intake", "exhaust", "delta", "gpu"):
            start = getattr(self, f"{source}_ramp_start_c")
            full = getattr(self, f"{source}_full_speed_c")
            critical = getattr(self, f"{source}_critical_c")
            if not start < full <= critical:
                raise ValueError(
                    f"{source} temperatures must satisfy ramp_start < full_speed <= critical"
                )
        if self.min_percent > self.max_percent:
            raise ValueError("min_percent must not exceed max_percent")
        if not self.min_percent <= self.gpu_curve_max_percent <= self.max_percent:
            raise ValueError("gpu_curve_max_percent must be inside the active fan range")
        return self


class WatchdogCheck(BaseModel):
    # disk: target is a file path on a host bind mount; the check writes and
    # fsyncs it, so a dead or read-only root device fails it (ssh does not:
    # sshd keeps answering from page cache).
    type: Literal["tcp", "http", "ssh", "disk"] = "tcp"
    target: str = "host.docker.internal:22"
    timeout_seconds: float = Field(default=1.0, ge=0.1, le=30.0)


class WatchdogConfig(BaseModel):
    enabled: bool = False
    keepalive_when_disabled: bool = True
    short_timeout_seconds: int = Field(default=120, ge=10, le=3600)
    long_timeout_seconds: int = Field(default=1500, ge=60, le=86400)
    feed_interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    unhealthy_failures_before_reset: int = Field(default=3, ge=1, le=100)
    gpus_expected: int = Field(default=0, ge=0, le=16)
    gpu_recovery_enabled: bool = False
    gpu_recovery_grace_seconds: int = Field(default=240, ge=60, le=1800)
    gpu_recovery_restart_containers: list[str] = Field(default_factory=list)
    ai_recovery_enabled: bool = False
    ai_recovery_min_failures: int = Field(default=3, ge=1, le=100)
    ai_recovery_cooldown_seconds: int = Field(default=900, ge=60, le=3600)
    ai_recovery_restart_containers: list[str] = Field(default_factory=list)
    checks: list[WatchdogCheck] = Field(default_factory=list)
    # Second reset path: the host's own hardware watchdog (chipset iTCO), fed under the
    # same health policy. None disables it. See hostwatchdog.py.
    host_device: str | None = None
    host_timeout_seconds: int = Field(default=180, ge=30, le=600)


class DisplayConfig(BaseModel):
    enabled: bool = True
    profile: Literal["system", "thermal", "power", "ai"] = "ai"
    refresh_interval_seconds: float = Field(default=15.0, ge=5.0, le=3600.0)
    title: str | None = None
    persist_to_eeprom: bool = True


class LedConfig(BaseModel):
    enabled: bool = False
    poll_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    warning_led_id: int = Field(default=0, ge=0, le=15)
    online_led_id: int = Field(default=1, ge=0, le=15)
    activity_led_id: int = Field(default=2, ge=0, le=15)
    off_mode: int = Field(default=0, ge=0, le=15)
    on_mode: int = Field(default=1, ge=0, le=15)
    fast_blink_mode: int = Field(default=2, ge=0, le=15)
    slow_blink_mode: int = Field(default=3, ge=0, le=15)
    gpu_activity_utilization_percent: float = Field(default=15.0, ge=0.0, le=100.0)
    gpu_activity_power_watts: float = Field(default=40.0, ge=0.0, le=1000.0)


class LlamaCppServerConfig(BaseModel):
    name: str
    gpu: str
    base_url: str
    expected_model: str


class LlamaCppConfig(BaseModel):
    enabled: bool = False
    timeout_seconds: float = Field(default=2.0, ge=0.2, le=30.0)
    servers: list[LlamaCppServerConfig] = Field(
        default_factory=lambda: [
            LlamaCppServerConfig(
                name="llama3.1:8b",
                gpu="2",
                base_url="http://llamacpp-llama31-pro:8080",
                expected_model="llama3.1:8b",
            ),
        ]
    )


class OllamaConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://ollama:11434"
    timeout_seconds: float = Field(default=8.0, ge=0.2, le=60.0)


class StrataEndpoint(BaseModel):
    name: str = Field(default="Strata", min_length=1, max_length=12)
    base_url: str


class StrataConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://host.docker.internal:18080"
    # Backends OpenAI-compatibles (Strata, Maya) que comparten las GPU y se turnan (llama-swap): el
    # estado es "up" si cualquiera responde. Vacio = solo base_url, con el nombre "Strata".
    endpoints: list[StrataEndpoint] = Field(default_factory=list)
    timeout_seconds: float = Field(default=5.0, ge=0.2, le=60.0)

    def resolved_endpoints(self) -> list[StrataEndpoint]:
        return self.endpoints or [StrataEndpoint(name="Strata", base_url=self.base_url)]


class FluxConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://host.docker.internal:7860"
    timeout_seconds: float = Field(default=5.0, ge=0.2, le=60.0)


class AppConfig(BaseModel):
    fans: FanConfig = Field(default_factory=FanConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    leds: LedConfig = Field(default_factory=LedConfig)
    llamacpp: LlamaCppConfig = Field(default_factory=LlamaCppConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    strata: StrataConfig = Field(default_factory=StrataConfig)
    flux: FluxConfig = Field(default_factory=FluxConfig)


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        cfg = AppConfig()
        save_config(path, cfg)
        return cfg
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "llamacpp" not in data and isinstance(data.get("ollama"), dict) and data["ollama"].get("enabled"):
        data["llamacpp"] = {"enabled": True}
    return AppConfig.model_validate(data)


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg.model_dump(mode="json"), fh, sort_keys=False)
