from __future__ import annotations

from .config import FanConfig
from .parser import ControllerStatus


def calculate_target_fan_percent(
    status: ControllerStatus,
    cfg: FanConfig,
    previous_percent: int | None,
    ai_generating: bool = False,
    gpu_idle_stop_active: bool = False,
) -> int:
    if cfg.mode == "manual":
        return clamp_active_fan_percent(cfg.manual_percent, cfg)

    if not status.ok:
        return calculate_fail_safe_target(cfg, previous_percent)

    temp = status.intake_temp_c
    if temp is None:
        return calculate_fail_safe_target(cfg, previous_percent)

    if gpu_idle_stop_active:
        return clamp_active_fan_percent(cfg.gpu_idle_stop_percent, cfg)

    previous = previous_percent or cfg.min_percent
    if temp <= cfg.target_temp_c - cfg.hysteresis_c:
        target = cfg.min_percent
    elif temp >= cfg.target_temp_c + cfg.hysteresis_c:
        degrees_over = temp - cfg.target_temp_c
        span = max(1.0, 15.0 - cfg.hysteresis_c)
        ratio = max(0.0, min(1.0, degrees_over / span))
        target = round(cfg.min_percent + (cfg.max_percent - cfg.min_percent) * ratio)
    else:
        target = previous

    if cfg.ai_load_assist and ai_generating:
        target += cfg.ai_load_boost_percent

    target = max(cfg.min_percent, min(cfg.max_percent, target))
    if target > previous:
        target = min(target, previous + cfg.max_step_percent)
    elif target < previous:
        target = max(target, previous - cfg.max_step_percent)
    return max(cfg.min_percent, min(cfg.max_percent, target))


def clamp_active_fan_percent(percent: int, cfg: FanConfig) -> int:
    return max(cfg.min_percent, min(cfg.max_percent, percent))


def calculate_fail_safe_target(cfg: FanConfig, previous_percent: int | None) -> int:
    if not cfg.fail_safe_ramp:
        return cfg.fail_safe_percent
    previous = previous_percent or cfg.min_percent
    target = min(cfg.fail_safe_percent, previous + cfg.max_step_percent)
    return max(cfg.min_percent, min(cfg.fail_safe_percent, target))
