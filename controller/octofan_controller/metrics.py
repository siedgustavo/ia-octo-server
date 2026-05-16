from __future__ import annotations

from prometheus_client import Gauge, generate_latest
from prometheus_client.core import REGISTRY

from .ollama import OllamaStatus
from .parser import ControllerStatus


controller_up = Gauge("octofan_controller_up", "Controller read success")
temperature = Gauge("octofan_temperature_celsius", "Temperature readings", ["source", "id"])
bme_humidity = Gauge("octofan_bme_humidity_percent", "BME280 humidity", ["id"])
bme_pressure = Gauge("octofan_bme_pressure_hpa", "BME280 pressure", ["id"])
fan_rpm = Gauge("octofan_fan_rpm", "Fan RPM", ["id"])
fan_percent = Gauge("octofan_fan_percent", "Fan percent", ["id"])
fan_pwm = Gauge("octofan_fan_pwm", "Fan PWM", ["id"])
psu_metric = Gauge("octofan_psu_metric", "PSU metrics", ["id", "model", "metric"])
watchdog_metric = Gauge("octofan_watchdog", "Watchdog values", ["metric"])
version_metric = Gauge("octofan_controller_version", "Controller versions", ["type"])
power_total = Gauge("octofan_power_ac_total_watts", "Total AC power")
ai_tps = Gauge("octofan_ai_tokens_per_second", "AI tokens per second", ["source"])
ai_models = Gauge("octofan_ai_running_models", "AI running models", ["source"])
target_fan = Gauge("octofan_target_fan_percent", "Last target case fan percent")


def update_metrics(status: ControllerStatus, ollama: OllamaStatus, current_target_fan: int | None) -> None:
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
        for metric in ("voltage_ac", "amperage_ac", "power_ac", "voltage_dc", "amperage_dc", "power_dc", "temp_1", "temp_2", "temp_3", "fan_rpm", "peak_power_ac"):
            value = getattr(psu, metric)
            if value is not None:
                psu_metric.labels(str(psu_id), psu.model, metric).set(value)
    power_total.set(status.power_ac_total_w)
    if status.watchdog_mode is not None:
        watchdog_metric.labels("mode").set(status.watchdog_mode)
    if status.watchdog_resets is not None:
        watchdog_metric.labels("resets").set(status.watchdog_resets)
    ai_tps.labels("ollama").set(ollama.tokens_per_second)
    ai_models.labels("ollama").set(ollama.running_models)


def metrics_payload() -> bytes:
    return generate_latest(REGISTRY)
