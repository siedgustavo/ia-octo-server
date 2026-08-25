from __future__ import annotations

import os
from pathlib import Path
import socket

from .config import DisplayConfig
from .llamacpp import LlamaCppStatus
from .nvidia import NvidiaStatus
from .ollama import OllamaStatus
from .parser import ControllerStatus


WIDTH = 20
BIG_WIDTH = 10
HEIGHT = 8
HOST_HOSTNAME_PATH = Path("/host/etc/hostname")
HOST_HOSTS_PATH = Path("/host/etc/hosts")


def fit(text: str, width: int = WIDTH) -> str:
    return text[:width].ljust(width)


def render_display(
    status: ControllerStatus,
    cfg: DisplayConfig,
    fan_percent: int | None,
    llamacpp: LlamaCppStatus,
    nvidia: NvidiaStatus | None = None,
    ollama: OllamaStatus | None = None,
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
        if _ollama_ai_health(ollama, llamacpp) is None:
            ai_health = "AI monitor off"
        else:
            ai_health = _ollama_ai_health(ollama, llamacpp)
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


def _ollama_ai_health(ollama: OllamaStatus | None, llamacpp: LlamaCppStatus) -> str | None:
    if ollama is not None and ollama.enabled:
        if not ollama.up:
            return "Ollama DOWN"
        return f"Ollama {ollama.running_models} model{'' if ollama.running_models == 1 else 's'} loaded"
    if llamacpp.ok:
        return "AI services OK"
    if not llamacpp.servers and llamacpp.error is None:
        return None
    return "AI degraded"


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

    hostname = _read_host_hostname() or socket.gethostname()
    candidates = {hostname, hostname.split(".", 1)[0]}

    for hosts_path in (HOST_HOSTS_PATH, Path("/etc/hosts")):
        for ip, aliases in _hosts_entries(hosts_path):
            if any(alias in candidates for alias in aliases):
                return ip

    try:
        addresses = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        for address in addresses:
            ip = address[4][0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "unavailable"


def _hosts_entries(path: Path) -> list[tuple[str, frozenset[str]]]:
    entries: list[tuple[str, frozenset[str]]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ip = parts[0]
        if ":" in ip:
            continue
        if ip.startswith("127."):
            continue
        entries.append((ip, frozenset(parts[1:])))
    return entries


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
