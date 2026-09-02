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
    type: Literal["tcp", "http", "ssh"] = "tcp"
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
    checks: list[WatchdogCheck] = Field(default_factory=list)


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


class AppConfig(BaseModel):
    fans: FanConfig = Field(default_factory=FanConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    leds: LedConfig = Field(default_factory=LedConfig)
    llamacpp: LlamaCppConfig = Field(default_factory=LlamaCppConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


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
