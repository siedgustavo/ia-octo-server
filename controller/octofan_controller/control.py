from __future__ import annotations

from dataclasses import dataclass

from .config import FanConfig
from .nvidia import NvidiaStatus
from .parser import ControllerStatus, is_sane_temperature


@dataclass(frozen=True)
class FanControlDecision:
    target_percent: int
    raw_target_percent: int
    reason: str
    temperature_delta_c: float | None = None
    intake_target_percent: int | None = None
    exhaust_target_percent: int | None = None
    delta_target_percent: int | None = None
    gpu_target_percent: int | None = None


def calculate_target_fan_percent(
    status: ControllerStatus,
    cfg: FanConfig,
    previous_percent: int | None,
    ai_generating: bool = False,
    gpu_idle_stop_active: bool = False,
    nvidia: NvidiaStatus | None = None,
) -> int:
    return calculate_fan_control_decision(
        status,
        cfg,
        previous_percent,
        ai_generating,
        gpu_idle_stop_active,
        nvidia,
    ).target_percent


def calculate_fan_control_decision(
    status: ControllerStatus,
    cfg: FanConfig,
    previous_percent: int | None,
    ai_generating: bool = False,
    gpu_idle_stop_active: bool = False,
    nvidia: NvidiaStatus | None = None,
) -> FanControlDecision:
    if not status.ok:
        if cfg.mode == "manual":
            target = clamp_active_fan_percent(cfg.manual_percent, cfg)
            return FanControlDecision(target, target, "manual")
        target = calculate_fail_safe_target(cfg, previous_percent)
        return FanControlDecision(target, cfg.fail_safe_percent, "controller_fail_safe")

    intake = status.intake_temp_c
    exhaust = status.exhaust_temp_c
    intake_target = _temperature_curve_target(
        intake, cfg.intake_ramp_start_c, cfg.intake_full_speed_c, cfg
    )
    exhaust_target = _temperature_curve_target(
        exhaust, cfg.exhaust_ramp_start_c, cfg.exhaust_full_speed_c, cfg
    )
    temperature_delta = None
    if intake is not None and exhaust is not None:
        temperature_delta = max(0.0, exhaust - intake)
    delta_target = _temperature_curve_target(
        temperature_delta,
        cfg.delta_ramp_start_c,
        cfg.delta_full_speed_c,
        cfg,
    )

    gpu_temperatures = []
    if nvidia is not None and nvidia.ok:
        gpu_temperatures = [
            gpu.temperature_gpu_c
            for gpu in nvidia.gpus
            if is_sane_temperature(gpu.temperature_gpu_c)
        ]
    max_gpu_temp = max(gpu_temperatures, default=None)
    gpu_target = _temperature_curve_target(
        max_gpu_temp,
        cfg.gpu_ramp_start_c,
        cfg.gpu_full_speed_c,
        cfg,
        cfg.gpu_curve_max_percent,
    )

    candidates = {
        "intake": intake_target,
        "exhaust": exhaust_target,
        "delta": delta_target,
        "gpu": gpu_target,
    }
    available = {name: target for name, target in candidates.items() if target is not None}
    if cfg.mode == "manual":
        target = clamp_active_fan_percent(cfg.manual_percent, cfg)
        auto_demand = max(available.values(), default=target)
        return FanControlDecision(
            target_percent=target,
            raw_target_percent=auto_demand,
            reason="manual",
            temperature_delta_c=temperature_delta,
            intake_target_percent=intake_target,
            exhaust_target_percent=exhaust_target,
            delta_target_percent=delta_target,
            gpu_target_percent=gpu_target,
        )
    if not available:
        target = calculate_fail_safe_target(cfg, previous_percent)
        return FanControlDecision(target, cfg.fail_safe_percent, "temperature_fail_safe")

    raw_target = max(available.values())
    reason = max(available, key=available.get)
    if cfg.ai_load_assist and ai_generating:
        raw_target += cfg.ai_load_boost_percent
        reason += "+ai_load"
    raw_target = clamp_active_fan_percent(raw_target, cfg)

    critical = (
        (intake is not None and intake >= cfg.intake_critical_c)
        or (exhaust is not None and exhaust >= cfg.exhaust_critical_c)
        or (temperature_delta is not None and temperature_delta >= cfg.delta_critical_c)
        or (max_gpu_temp is not None and max_gpu_temp >= cfg.gpu_critical_c)
    )
    if critical:
        raw_target = cfg.max_percent
        target = cfg.max_percent
        reason = "critical_" + reason
    elif gpu_idle_stop_active:
        raw_target = clamp_active_fan_percent(cfg.gpu_idle_stop_percent, cfg)
        target = raw_target
        reason = "gpu_idle"
    else:
        target = _slew_target(raw_target, previous_percent, cfg)

    return FanControlDecision(
        target_percent=target,
        raw_target_percent=raw_target,
        reason=reason,
        temperature_delta_c=temperature_delta,
        intake_target_percent=intake_target,
        exhaust_target_percent=exhaust_target,
        delta_target_percent=delta_target,
        gpu_target_percent=gpu_target,
    )


def _temperature_curve_target(
    temperature_c: float | None,
    ramp_start_c: float,
    full_speed_c: float,
    cfg: FanConfig,
    curve_max_percent: int | None = None,
) -> int | None:
    if not is_sane_temperature(temperature_c):
        return None
    if temperature_c <= ramp_start_c:
        return cfg.min_percent
    maximum = curve_max_percent if curve_max_percent is not None else cfg.max_percent
    if temperature_c >= full_speed_c:
        return maximum
    span = max(0.1, full_speed_c - ramp_start_c)
    ratio = (temperature_c - ramp_start_c) / span
    return round(cfg.min_percent + (maximum - cfg.min_percent) * ratio)


def _slew_target(raw_target: int, previous_percent: int | None, cfg: FanConfig) -> int:
    previous = previous_percent if previous_percent is not None else cfg.min_percent
    if abs(raw_target - previous) <= cfg.target_deadband_percent:
        return clamp_active_fan_percent(previous, cfg)
    if raw_target > previous:
        return min(raw_target, previous + cfg.max_step_percent)
    return max(raw_target, previous - cfg.max_down_step_percent)


def clamp_active_fan_percent(percent: int, cfg: FanConfig) -> int:
    return max(cfg.min_percent, min(cfg.max_percent, percent))


def calculate_fail_safe_target(cfg: FanConfig, previous_percent: int | None) -> int:
    if not cfg.fail_safe_ramp:
        return cfg.fail_safe_percent
    previous = previous_percent if previous_percent is not None else cfg.min_percent
    target = min(cfg.fail_safe_percent, previous + cfg.max_step_percent)
    return max(cfg.min_percent, min(cfg.fail_safe_percent, target))
