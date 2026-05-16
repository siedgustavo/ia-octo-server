from __future__ import annotations

import os
import re
import subprocess
from csv import reader
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
            return parse_nvidia_smi_csv(MOCK_NVIDIA_SMI, GPU_QUERY_FIELDS)
        fields = list(GPU_QUERY_FIELDS)
        dropped_fields: list[str] = []
        try:
            while fields:
                query = ",".join(fields)
                try:
                    raw = subprocess.check_output(
                        [self.binary, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                        text=True,
                        stderr=subprocess.STDOUT,
                        timeout=self.timeout,
                    )
                    status = parse_nvidia_smi_csv(raw, fields)
                    if dropped_fields:
                        skipped = ", ".join(dropped_fields)
                        status.error = f"Skipped unsupported nvidia-smi fields: {skipped}"
                    return status
                except subprocess.CalledProcessError as exc:
                    output = exc.output or ""
                    invalid = _invalid_query_field(output)
                    if invalid and invalid in fields:
                        fields.remove(invalid)
                        dropped_fields.append(invalid)
                        continue
                    raise
        except Exception as exc:
            return NvidiaStatus(ok=False, gpus=[], error=str(exc))


def parse_nvidia_smi_csv(raw: str, fields: list[str] | None = None) -> NvidiaStatus:
    fields = fields or GPU_QUERY_FIELDS
    gpus: list[GpuStatus] = []
    try:
        for row in reader(raw.splitlines()):
            if not row:
                continue
            values = {field: row[index].strip() for index, field in enumerate(fields) if index < len(row)}
            gpus.append(
                GpuStatus(
                    index=int(_num(values.get("index", "")) or 0),
                    uuid=values.get("uuid", ""),
                    name=values.get("name", ""),
                    pci_bus_id=values.get("pci.bus_id", ""),
                    driver_version=_str(values.get("driver_version", "")),
                    vbios_version=_str(values.get("vbios_version", "")),
                    temperature_gpu_c=_num(values.get("temperature.gpu", "")),
                    temperature_memory_c=_num(values.get("temperature.memory", "")),
                    fan_speed_percent=_num(values.get("fan.speed", "")),
                    utilization_gpu_percent=_num(values.get("utilization.gpu", "")),
                    utilization_memory_percent=_num(values.get("utilization.memory", "")),
                    memory_total_mib=_num(values.get("memory.total", "")),
                    memory_used_mib=_num(values.get("memory.used", "")),
                    memory_free_mib=_num(values.get("memory.free", "")),
                    power_draw_watts=_num(values.get("power.draw", "")),
                    power_limit_watts=_num(values.get("power.limit", "")),
                    clock_graphics_mhz=_num(values.get("clocks.current.graphics", "")),
                    clock_memory_mhz=_num(values.get("clocks.current.memory", "")),
                    clock_max_graphics_mhz=_num(values.get("clocks.max.graphics", "")),
                    clock_max_memory_mhz=_num(values.get("clocks.max.memory", "")),
                    pstate=_str(values.get("pstate", "")),
                    compute_mode=_str(values.get("compute_mode", "")),
                    display_active=_str(values.get("display_active", "")),
                    pcie_link_gen_current=_num(values.get("pcie.link.gen.current", "")),
                    pcie_link_gen_max=_num(values.get("pcie.link.gen.max", "")),
                    pcie_link_width_current=_num(values.get("pcie.link.width.current", "")),
                    pcie_link_width_max=_num(values.get("pcie.link.width.max", "")),
                    encoder_sessions=_num(values.get("encoder.stats.sessionCount", "")),
                    decoder_sessions=_num(values.get("decoder.stats.sessionCount", "")),
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


def _invalid_query_field(output: str) -> str | None:
    match = re.search(r'Field "([^"]+)" is not a valid field', output)
    return match.group(1) if match else None
