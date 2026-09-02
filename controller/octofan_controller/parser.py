from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FanStatus:
    id: int
    rpm: int | None = None
    default_pwm: int | None = None
    current_pwm: int | None = None
    max_rpm: int | None = None
    percent: float | None = None


@dataclass
class PsuStatus:
    id: int
    model: str
    voltage_ac: float | None = None
    amperage_ac: float | None = None
    power_ac: float | None = None
    voltage_dc: float | None = None
    amperage_dc: float | None = None
    power_dc: float | None = None
    temp_1: float | None = None
    temp_2: float | None = None
    temp_3: float | None = None
    fan_rpm: float | None = None
    peak_power_ac: float | None = None
    peak_amperage_dc: float | None = None
    energy_ac_kwh: float | None = None


@dataclass
class BmeStatus:
    id: int
    temp_c: float | None = None
    humidity: float | None = None
    pressure_hpa: float | None = None


@dataclass
class ControllerStatus:
    ok: bool = True
    raw: str = ""
    error: str | None = None
    serial: str | None = None
    version_cli: float | None = None
    version_fw: float | None = None
    version_hw: float | None = None
    version_boot: float | None = None
    temperatures: dict[int, float] = field(default_factory=dict)
    voltages: dict[int, float] = field(default_factory=dict)
    fans: dict[int, FanStatus] = field(default_factory=dict)
    psus: dict[int, PsuStatus] = field(default_factory=dict)
    bme280: dict[int, BmeStatus] = field(default_factory=dict)
    watchdog_mode: int | None = None
    watchdog_short_timeout: int | None = None
    watchdog_long_timeout: int | None = None
    watchdog_resets: int | None = None

    @property
    def intake_temp_c(self) -> float | None:
        bme = self.bme280.get(0)
        if bme and is_sane_temperature(bme.temp_c):
            return bme.temp_c
        if is_sane_temperature(self.temperatures.get(0)):
            return self.temperatures.get(0)
        for bme in self.bme280.values():
            if is_sane_temperature(bme.temp_c):
                return bme.temp_c
        for value in self.temperatures.values():
            if is_sane_temperature(value):
                return value
        return None

    @property
    def exhaust_temp_c(self) -> float | None:
        bme = self.bme280.get(1)
        if bme and is_sane_temperature(bme.temp_c):
            return bme.temp_c
        if is_sane_temperature(self.temperatures.get(1)):
            return self.temperatures.get(1)
        return self.intake_temp_c

    @property
    def power_ac_total_w(self) -> float:
        return sum(psu.power_ac or 0 for psu in self.psus.values())


RE_VERSION = re.compile(r"VERSION-(CLI|FW|HW|BOOT):\s+([0-9.]+)")
RE_SERIAL = re.compile(r"Serial No:?\s+(0x[0-9A-Fa-f]+)")
RE_TEMP = re.compile(r"Temperature No\.\s+(\d+)\s+Celsius:\s+(-?\d+(?:\.\d+)?)")
RE_VOLT = re.compile(r"Voltage No\.\s+(\d+)\s+Volt:\s+(-?\d+(?:\.\d+)?)")
RE_WD_MODE = re.compile(r"Watch-?Dog Mode:\s+(\d+)", re.IGNORECASE)
RE_WD_SHORT = re.compile(r"Watchdog short tim?e?out:\s+(\d+)")
RE_WD_LONG = re.compile(r"Watchdog long timeout:\s+(\d+)")
RE_WD_RESETS = re.compile(r"(?:Watchdog Resets|Reset Counter)\s*(?:=|:)\s*(\d+)")
RE_FAN = re.compile(r"FAN No\.\s+(\d+)\s+(RPM|Default PWM|Current PWM|max RPM|RPM in percent):\s+([0-9.]+)")
RE_BME = re.compile(r"BME280 No\.\s+(\d+)\s+(Temp|Humid|Press):\s+(-?\d+(?:\.\d+)?)")
RE_PSU = re.compile(
    r"(?P<model>.+?)\s+PSU No\.\s+(?P<id>\d+)\s+"
    r"(?P<metric>Vac|Iac|Pac|Vdc|Idc|Pdc|T1|T2|T3|FAN|Peak Pac|Peak Idc|Wac):\s+"
    r"(?P<value>-?\d+(?:\.\d+)?)"
)


def parse_controller_output(raw: str) -> ControllerStatus:
    status = ControllerStatus(raw=raw)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        if match := RE_SERIAL.search(line):
            status.serial = match.group(1)
        for match in RE_VERSION.finditer(line):
            setattr(status, f"version_{match.group(1).lower()}", float(match.group(2)))
        if match := RE_TEMP.search(line):
            status.temperatures[int(match.group(1))] = float(match.group(2))
        if match := RE_VOLT.search(line):
            status.voltages[int(match.group(1))] = float(match.group(2))
        if match := RE_WD_MODE.search(line):
            status.watchdog_mode = int(match.group(1))
        if match := RE_WD_SHORT.search(line):
            status.watchdog_short_timeout = int(match.group(1))
        if match := RE_WD_LONG.search(line):
            status.watchdog_long_timeout = int(match.group(1))
        if match := RE_WD_RESETS.search(line):
            status.watchdog_resets = int(match.group(1))
        if match := RE_FAN.search(line):
            fan_id = int(match.group(1))
            fan = status.fans.setdefault(fan_id, FanStatus(id=fan_id))
            metric = match.group(2)
            value = float(match.group(3))
            if metric == "RPM":
                fan.rpm = int(value)
            elif metric == "Default PWM":
                fan.default_pwm = int(value)
            elif metric == "Current PWM":
                fan.current_pwm = int(value)
            elif metric == "max RPM":
                fan.max_rpm = int(value)
            elif metric == "RPM in percent":
                fan.percent = value
        if match := RE_BME.search(line):
            sensor_id = int(match.group(1))
            bme = status.bme280.setdefault(sensor_id, BmeStatus(id=sensor_id))
            value = float(match.group(3))
            if match.group(2) == "Temp":
                bme.temp_c = value
            elif match.group(2) == "Humid":
                bme.humidity = value
            elif match.group(2) == "Press":
                bme.pressure_hpa = value
        if match := RE_PSU.search(line):
            psu_id = int(match.group("id"))
            psu = status.psus.setdefault(psu_id, PsuStatus(id=psu_id, model=match.group("model")))
            metric = match.group("metric")
            value = float(match.group("value"))
            field_name = {
                "Vac": "voltage_ac",
                "Iac": "amperage_ac",
                "Pac": "power_ac",
                "Vdc": "voltage_dc",
                "Idc": "amperage_dc",
                "Pdc": "power_dc",
                "T1": "temp_1",
                "T2": "temp_2",
                "T3": "temp_3",
                "FAN": "fan_rpm",
                "Peak Pac": "peak_power_ac",
                "Peak Idc": "peak_amperage_dc",
                "Wac": "energy_ac_kwh",
            }[metric]
            setattr(psu, field_name, value)
    return status


def is_sane_temperature(value: float | None) -> bool:
    return value is not None and -20 <= value <= 120
