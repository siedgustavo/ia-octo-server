from __future__ import annotations

from prometheus_client import Gauge, generate_latest
from prometheus_client.core import REGISTRY

from .nvidia import NvidiaStatus
from .parser import ControllerStatus
from .rpc import RpcStatus


controller_up = Gauge("octofan_controller_up", "Controller read success")
temperature = Gauge("octofan_temperature_celsius", "Temperature readings", ["source", "id"])
intake_temperature = Gauge("octofan_intake_temperature_celsius", "Selected sane intake temperature")
exhaust_temperature = Gauge("octofan_exhaust_temperature_celsius", "Selected sane exhaust temperature")
bme_humidity = Gauge("octofan_bme_humidity_percent", "BME280 humidity", ["id"])
bme_pressure = Gauge("octofan_bme_pressure_hpa", "BME280 pressure", ["id"])
controller_voltage = Gauge("octofan_voltage_volts", "Controller voltage readings", ["id"])
fan_rpm = Gauge("octofan_fan_rpm", "Fan RPM", ["id"])
fan_percent = Gauge("octofan_fan_percent", "Fan percent", ["id"])
fan_pwm = Gauge("octofan_fan_pwm", "Fan PWM", ["id"])
psu_metric = Gauge("octofan_psu_metric", "PSU metrics", ["id", "model", "metric"])
watchdog_metric = Gauge("octofan_watchdog", "Watchdog values", ["metric"])
version_metric = Gauge("octofan_controller_version", "Controller versions", ["type"])
power_total = Gauge("octofan_power_ac_total_watts", "Total AC power")
rpc_up = Gauge("octofan_rpc_backends_up", "llama.cpp RPC backends up")
rpc_total = Gauge("octofan_rpc_backends_total", "llama.cpp RPC backends configured")
rpc_backend_up = Gauge("octofan_rpc_backend_up", "llama.cpp RPC backend TCP health", ["name", "gpu", "target"])
target_fan = Gauge("octofan_target_fan_percent", "Last target case fan percent")
nvidia_up = Gauge("octofan_nvidia_smi_up", "nvidia-smi read success")
nvidia_info = Gauge("octofan_nvidia_gpu_info", "NVIDIA GPU info", ["index", "uuid", "name", "pci_bus_id", "driver_version", "vbios_version"])
nvidia_metric = Gauge("octofan_nvidia_gpu_metric", "NVIDIA GPU metric from nvidia-smi", ["index", "uuid", "name", "metric"])


def update_metrics(status: ControllerStatus, current_target_fan: int | None, nvidia: NvidiaStatus | None = None, rpc: RpcStatus | None = None) -> None:
    controller_up.set(1 if status.ok else 0)
    if current_target_fan is not None:
        target_fan.set(current_target_fan)
    if status.version_cli is not None:
        version_metric.labels("cli").set(status.version_cli)
    if status.version_fw is not None:
        version_metric.labels("fw").set(status.version_fw)
    if status.version_hw is not None:
        version_metric.labels("hw").set(status.version_hw)
    if status.version_boot is not None:
        version_metric.labels("boot").set(status.version_boot)
    for sensor_id, value in status.temperatures.items():
        temperature.labels("temperature", str(sensor_id)).set(value)
    if status.intake_temp_c is not None:
        intake_temperature.set(status.intake_temp_c)
    if status.exhaust_temp_c is not None:
        exhaust_temperature.set(status.exhaust_temp_c)
    for voltage_id, value in status.voltages.items():
        controller_voltage.labels(str(voltage_id)).set(value)
    for sensor_id, bme in status.bme280.items():
        if bme.temp_c is not None:
            temperature.labels("bme280", str(sensor_id)).set(bme.temp_c)
        if bme.humidity is not None:
            bme_humidity.labels(str(sensor_id)).set(bme.humidity)
        if bme.pressure_hpa is not None:
            bme_pressure.labels(str(sensor_id)).set(bme.pressure_hpa)
    for fan_id, fan in status.fans.items():
        label = str(fan_id)
        if fan.rpm is not None:
            fan_rpm.labels(label).set(fan.rpm)
        if fan.percent is not None:
            fan_percent.labels(label).set(fan.percent)
        if fan.current_pwm is not None:
            fan_pwm.labels(label).set(fan.current_pwm)
    for psu_id, psu in status.psus.items():
        for metric in (
            "voltage_ac",
            "amperage_ac",
            "power_ac",
            "voltage_dc",
            "amperage_dc",
            "power_dc",
            "temp_1",
            "temp_2",
            "temp_3",
            "fan_rpm",
            "peak_power_ac",
            "peak_amperage_dc",
            "energy_ac_kwh",
        ):
            value = getattr(psu, metric)
            if value is not None:
                psu_metric.labels(str(psu_id), psu.model, metric).set(value)
    power_total.set(status.power_ac_total_w)
    if status.watchdog_mode is not None:
        watchdog_metric.labels("mode").set(status.watchdog_mode)
    if status.watchdog_resets is not None:
        watchdog_metric.labels("resets").set(status.watchdog_resets)
    if rpc is not None:
        rpc_up.set(rpc.up)
        rpc_total.set(rpc.total)
        for backend in rpc.backends:
            rpc_backend_up.labels(backend.name, str(backend.gpu), backend.target).set(1 if backend.ok else 0)
    if nvidia is not None:
        nvidia_up.set(1 if nvidia.ok else 0)
        for gpu in nvidia.gpus:
            labels = (str(gpu.index), gpu.uuid, gpu.name)
            nvidia_info.labels(str(gpu.index), gpu.uuid, gpu.name, gpu.pci_bus_id, gpu.driver_version or "", gpu.vbios_version or "").set(1)
            for metric_name in (
                "temperature_gpu_c",
                "temperature_memory_c",
                "fan_speed_percent",
                "utilization_gpu_percent",
                "utilization_memory_percent",
                "memory_total_mib",
                "memory_used_mib",
                "memory_free_mib",
                "power_draw_watts",
                "power_limit_watts",
                "clock_graphics_mhz",
                "clock_memory_mhz",
                "clock_max_graphics_mhz",
                "clock_max_memory_mhz",
                "pcie_link_gen_current",
                "pcie_link_gen_max",
                "pcie_link_width_current",
                "pcie_link_width_max",
                "encoder_sessions",
                "decoder_sessions",
            ):
                value = getattr(gpu, metric_name)
                if value is not None:
                    nvidia_metric.labels(*labels, metric_name).set(value)


def metrics_payload() -> bytes:
    return generate_latest(REGISTRY)
