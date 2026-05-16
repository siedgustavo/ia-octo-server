from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class FanConfig(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    target_temp_c: float = 38.0
    hysteresis_c: float = 2.0
    min_percent: int = Field(default=35, ge=1, le=100)
    max_percent: int = Field(default=100, ge=1, le=100)
    manual_percent: int = Field(default=70, ge=1, le=100)
    max_step_percent: int = Field(default=8, ge=1, le=100)
    ai_load_assist: bool = True
    ai_load_boost_percent: int = Field(default=10, ge=0, le=50)
    fail_safe_percent: int = Field(default=100, ge=1, le=100)
    poll_interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)


class WatchdogCheck(BaseModel):
    type: Literal["tcp", "http"] = "tcp"
    target: str = "host.docker.internal:22"
    timeout_seconds: float = Field(default=1.0, ge=0.1, le=30.0)


class WatchdogConfig(BaseModel):
    enabled: bool = False
    short_timeout_seconds: int = Field(default=120, ge=10, le=3600)
    long_timeout_seconds: int = Field(default=1500, ge=60, le=86400)
    feed_interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    checks: list[WatchdogCheck] = Field(default_factory=list)


class DisplayConfig(BaseModel):
    enabled: bool = True
    profile: Literal["system", "thermal", "power", "ai"] = "ai"
    refresh_interval_seconds: float = Field(default=15.0, ge=5.0, le=3600.0)
    title: str = "OCTOFAN AI"


class OllamaConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://host.docker.internal:11434"
    timeout_seconds: float = Field(default=2.0, ge=0.2, le=30.0)


class AppConfig(BaseModel):
    fans: FanConfig = Field(default_factory=FanConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        cfg = AppConfig()
        save_config(path, cfg)
        return cfg
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return AppConfig.model_validate(data)


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg.model_dump(mode="json"), fh, sort_keys=False)
