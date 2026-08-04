from __future__ import annotations

import os
from pathlib import Path
import socket

from .config import DisplayConfig
from .llamacpp import LlamaCppStatus
from .nvidia import NvidiaStatus
from .parser import ControllerStatus


WIDTH = 20
BIG_WIDTH = 10
HEIGHT = 8
HOST_HOSTNAME_PATH = Path("/host/etc/hostname")


def fit(text: str, width: int = WIDTH) -> str:
    return text[:width].ljust(width)


def render_display(
    status: ControllerStatus,
    cfg: DisplayConfig,
    fan_percent: int | None,
    llamacpp: LlamaCppStatus,
    nvidia: NvidiaStatus | None = None,
) -> list[str]:
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
        ai_health = "AI services OK" if llamacpp.ok else "AI degraded"
        lines += [
            fit(f"IP {resolve_host_ip()}"),
            fit(ai_health),
            fit(_fmt_gpu(nvidia)),
            fit(f"In {intake} Fan {fan_percent or 0}%"),
            fit(f"Power {power}"),
        ]
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


def resolve_host_ip() -> str:
    override = os.getenv("OCTOFAN_DISPLAY_IP", "").strip()
    if override:
        return override

    hostname = _read_host_hostname()
    if hostname:
        try:
            addresses = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
            for address in addresses:
                ip = address[4][0]
                if not ip.startswith("127."):
                    return ip
        except OSError:
            pass
    return "unavailable"


def _fmt_gpu(nvidia: NvidiaStatus | None) -> str:
    if not nvidia or not nvidia.ok or not nvidia.gpus:
        return "GPU telemetry n/a"
    temperatures = [gpu.temperature_gpu_c for gpu in nvidia.gpus if gpu.temperature_gpu_c is not None]
    utilizations = [gpu.utilization_gpu_percent for gpu in nvidia.gpus if gpu.utilization_gpu_percent is not None]
    temperature = f"{max(temperatures):.0f}C" if temperatures else "--C"
    utilization = f"{max(utilizations):.0f}%" if utilizations else "--%"
    return f"GPU {temperature} Load {utilization}"


def _read_host_hostname() -> str | None:
    try:
        return HOST_HOSTNAME_PATH.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
