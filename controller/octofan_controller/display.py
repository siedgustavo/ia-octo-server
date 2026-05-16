from __future__ import annotations

import socket

from .config import DisplayConfig
from .ollama import OllamaStatus
from .parser import ControllerStatus


WIDTH = 20
BIG_WIDTH = 10
HEIGHT = 8


def fit(text: str, width: int = WIDTH) -> str:
    return text[:width].ljust(width)


def render_display(status: ControllerStatus, cfg: DisplayConfig, fan_percent: int | None, ollama: OllamaStatus) -> list[str]:
    lines = [fit(cfg.title, BIG_WIDTH), fit("")]
    host = socket.gethostname()
    intake = _fmt_temp(status.intake_temp_c)
    exhaust = _fmt_temp(status.exhaust_temp_c)
    power = f"{status.power_ac_total_w:.0f}W" if status.power_ac_total_w else "--W"

    if cfg.profile == "thermal":
        lines += [fit(f"In {intake} Out {exhaust}"), fit(f"Fan {fan_percent or 0}%"), fit(f"BME {len(status.bme280)} PSU {len(status.psus)}")]
    elif cfg.profile == "power":
        lines += [fit(f"Power {power}"), fit(f"PSUs {len(status.psus)}"), fit(f"FW {status.version_fw or '-'} HW {status.version_hw or '-'}")]
    elif cfg.profile == "ai":
        tps = f"{ollama.tokens_per_second:.1f} tok/s" if ollama.ok else "AI offline"
        lines += [fit(tps), fit(f"Models {ollama.running_models}"), fit(f"In {intake} Fan {fan_percent or 0}%"), fit(f"Power {power}")]
    else:
        lines += [fit(host), fit(f"FW {status.version_fw or '-'} HW {status.version_hw or '-'}"), fit(f"In {intake} Out {exhaust}"), fit(f"Fan {fan_percent or 0}%")]

    while len(lines) < HEIGHT:
        lines.append(fit(""))
    return lines[:HEIGHT]


def _fmt_temp(value: float | None) -> str:
    return "--C" if value is None else f"{value:.0f}C"
