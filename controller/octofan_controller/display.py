from __future__ import annotations

import os
from pathlib import Path
import socket

from .config import DisplayConfig
from .ai_runtime import AIStatus
from .parser import ControllerStatus


WIDTH = 20
BIG_WIDTH = 10
HEIGHT = 8
HOST_HOSTNAME_PATH = Path("/host/etc/hostname")


def fit(text: str, width: int = WIDTH) -> str:
    return text[:width].ljust(width)


def render_display(status: ControllerStatus, cfg: DisplayConfig, fan_percent: int | None, ai: AIStatus) -> list[str]:
    lines = [fit(resolve_display_title(cfg), BIG_WIDTH), fit("")]
    host = socket.gethostname()
    intake = _fmt_temp(status.intake_temp_c)
    exhaust = _fmt_temp(status.exhaust_temp_c)
    power = f"{status.power_ac_total_w:.0f}W" if status.power_ac_total_w else "--W"

    if cfg.profile == "thermal":
        lines += [fit(f"In {intake} Out {exhaust}"), fit(f"Fan {fan_percent or 0}%"), fit(f"BME {len(status.bme280)} PSU {len(status.psus)}")]
    elif cfg.profile == "power":
        lines += [fit(f"Power {power}"), fit(f"PSUs {len(status.psus)}"), fit(f"FW {status.version_fw or '-'} HW {status.version_hw or '-'}")]
    elif cfg.profile == "ai":
        if not ai.ok:
            tps = "AI offline"
        elif ai.tokens_per_second_available and ai.tokens_per_second is not None:
            tps = f"{ai.tokens_per_second:.1f} tok/s"
        else:
            tps = "TPS n/a"
        lines += [fit(tps), fit(f"Models {ai.available_models}/{ai.running_models}"), fit(f"In {intake} Fan {fan_percent or 0}%"), fit(f"Power {power}")]
    else:
        lines += [fit(host), fit(f"FW {status.version_fw or '-'} HW {status.version_hw or '-'}"), fit(f"In {intake} Out {exhaust}"), fit(f"Fan {fan_percent or 0}%")]

    while len(lines) < HEIGHT:
        lines.append(fit(""))
    return lines[:HEIGHT]


def _fmt_temp(value: float | None) -> str:
    return "--C" if value is None else f"{value:.0f}C"


def resolve_display_title(cfg: DisplayConfig) -> str:
    if cfg.title:
        return cfg.title
    hostname = (
        os.getenv("OCTOFAN_DISPLAY_HOSTNAME")
        or _read_host_hostname()
        or socket.gethostname()
    )
    return hostname.split(".", 1)[0].upper()


def _read_host_hostname() -> str | None:
    try:
        return HOST_HOSTNAME_PATH.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
