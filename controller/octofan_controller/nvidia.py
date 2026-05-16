from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass


GPU_QUERY_FIELDS = [
    "index",
    "uuid",
    "name",
    "pci.bus_id",
    "driver_version",
    "vbios_version",
    "temperature.gpu",
    "temperature.memory",
    "fan.speed",
    "utilization.gpu",
    "utilization.memory",
    "memory.total",
    "memory.used",
    "memory.free",
    "power.draw",
    "power.limit",
    "clocks.current.graphics",
    "clocks.current.memory",
    "clocks.max.graphics",
    "clocks.max.memory",
    "pstate",
    "compute_mode",
    "display_active",
    "pcie.link.gen.current",
    "pcie.link.gen.max",
    "pcie.link.width.current",
    "pcie.link.width.max",
    "encoder.stats.sessionCount",
    "decoder.stats.sessionCount",
]


MOCK_NVIDIA_SMI = """0, GPU-mock-0, NVIDIA GeForce RTX 3060, 00000000:02:00.0, 595.71.05, 94.06.25.00.01, 36, N/A, 0, 0, 0, 12288, 1, 12287, 6.10, 170.00, 210, 405, 1837, 7501, P8, Default, Disabled, 1, 4, 16, 16, 0, 0
1, GPU-mock-1, NVIDIA GeForce RTX 3060, 00000000:03:00.0, 595.71.05, 94.06.25.00.02, 38, N/A, 0, 0, 0, 12288, 1, 12287, 10.20, 170.00, 210, 405, 1837, 7501, P8, Default, Disabled, 1, 4, 16, 16, 0, 0"""


@dataclass
class GpuStatus:
    index: int
    uuid: str
    name: str
    pci_bus_id: str
    driver_version: str | None = None
    vbios_version: str | None = None
    temperature_gpu_c: float | None = None
    temperature_memory_c: float | None = None
    fan_speed_percent: float | None = None
    utilization_gpu_percent: float | None = None
    utilization_memory_percent: float | None = None
    memory_total_mib: float | None = None
    memory_used_mib: float | None = None
    memory_free_mib: float | None = None
    power_draw_watts: float | None = None
    power_limit_watts: float | None = None
    clock_graphics_mhz: float | None = None
    clock_memory_mhz: float | None = None
    clock_max_graphics_mhz: float | None = None
    clock_max_memory_mhz: float | None = None
    pstate: str | None = None
    compute_mode: str | None = None
    display_active: str | None = None
    pcie_link_gen_current: float | None = None
    pcie_link_gen_max: float | None = None
    pcie_link_width_current: float | None = None
    pcie_link_width_max: float | None = None
    encoder_sessions: float | None = None
    decoder_sessions: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NvidiaStatus:
    ok: bool
    gpus: list[GpuStatus]
    error: str | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "error": self.error, "gpus": [gpu.to_dict() for gpu in self.gpus]}


class NvidiaSmi:
    def __init__(self, binary: str = "nvidia-smi", timeout: float = 5.0) -> None:
        self.binary = binary
        self.timeout = timeout
        self.mock = os.getenv("NVIDIA_SMI_MOCK", os.getenv("OCTOFAN_MOCK", "0")) == "1"

    def status(self) -> NvidiaStatus:
        if self.mock:
            return parse_nvidia_smi_csv(MOCK_NVIDIA_SMI)
        query = ",".join(GPU_QUERY_FIELDS)
        try:
            raw = subprocess.check_output(
                [self.binary, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
            )
            return parse_nvidia_smi_csv(raw)
        except Exception as exc:
            return NvidiaStatus(ok=False, gpus=[], error=str(exc))


def parse_nvidia_smi_csv(raw: str) -> NvidiaStatus:
    gpus: list[GpuStatus] = []
    try:
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split(",")]
            while len(parts) < len(GPU_QUERY_FIELDS):
                parts.append("")
            gpus.append(
                GpuStatus(
                    index=int(_num(parts[0]) or 0),
                    uuid=parts[1],
                    name=parts[2],
                    pci_bus_id=parts[3],
                    driver_version=_str(parts[4]),
                    vbios_version=_str(parts[5]),
                    temperature_gpu_c=_num(parts[6]),
                    temperature_memory_c=_num(parts[7]),
                    fan_speed_percent=_num(parts[8]),
                    utilization_gpu_percent=_num(parts[9]),
                    utilization_memory_percent=_num(parts[10]),
                    memory_total_mib=_num(parts[11]),
                    memory_used_mib=_num(parts[12]),
                    memory_free_mib=_num(parts[13]),
                    power_draw_watts=_num(parts[14]),
                    power_limit_watts=_num(parts[15]),
                    clock_graphics_mhz=_num(parts[16]),
                    clock_memory_mhz=_num(parts[17]),
                    clock_max_graphics_mhz=_num(parts[18]),
                    clock_max_memory_mhz=_num(parts[19]),
                    pstate=_str(parts[20]),
                    compute_mode=_str(parts[21]),
                    display_active=_str(parts[22]),
                    pcie_link_gen_current=_num(parts[23]),
                    pcie_link_gen_max=_num(parts[24]),
                    pcie_link_width_current=_num(parts[25]),
                    pcie_link_width_max=_num(parts[26]),
                    encoder_sessions=_num(parts[27]),
                    decoder_sessions=_num(parts[28]),
                )
            )
    except Exception as exc:
        return NvidiaStatus(ok=False, gpus=gpus, error=str(exc))
    return NvidiaStatus(ok=True, gpus=gpus)


def _num(value: str) -> float | None:
    value = value.strip()
    if not value or value.upper() in {"N/A", "[N/A]"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _str(value: str) -> str | None:
    value = value.strip()
    return None if not value or value.upper() in {"N/A", "[N/A]"} else value
