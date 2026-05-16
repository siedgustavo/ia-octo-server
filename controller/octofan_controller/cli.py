from __future__ import annotations

import os
import subprocess
from threading import Lock
from pathlib import Path

from .parser import ControllerStatus, parse_controller_output


MOCK_OUTPUT = """Serial No: 0x0102030405060708090A
VERSION-CLI: 1.0
VERSION-FW: 3.0
VERSION-HW: 1.2
VERSION-BOOT: 1.0
Temperature No. 0 Celsius: 31
Temperature No. 1 Celsius: 39
Watchdog Mode: 1
Watchdog short timeout: 120
Watchdog long timeout: 1500
Watchdog Resets: 0
PSMI(DPS1200-compat.) PSU No. 0 Vac: 229.9
PSMI(DPS1200-compat.) PSU No. 0 Iac: 3.10
PSMI(DPS1200-compat.) PSU No. 0 Pac: 692.0
PSMI(DPS1200-compat.) PSU No. 0 Vdc: 12.10
PSMI(DPS1200-compat.) PSU No. 0 Idc: 55.0
PSMI(DPS1200-compat.) PSU No. 0 Pdc: 665.5
PSMI(DPS1200-compat.) PSU No. 0 T1: 36.0
PSMI(DPS1200-compat.) PSU No. 0 T2: 44.0
PSMI(DPS1200-compat.) PSU No. 0 FAN: 4200
BME280 No. 0 Temp: 32.50
BME280 No. 0 Humid: 41.20
BME280 No. 0 Press: 1011.42
BME280 No. 1 Temp: 40.20
BME280 No. 1 Humid: 36.20
BME280 No. 1 Press: 1010.91
FAN No. 0 RPM: 3100
FAN No. 0 Default PWM: 127
FAN No. 0 Current PWM: 153
FAN No. 0 max RPM: 5100
FAN No. 0 RPM in percent: 61
FAN No. 1 RPM: 3050
FAN No. 1 Default PWM: 127
FAN No. 1 Current PWM: 153
FAN No. 1 max RPM: 5000
FAN No. 1 RPM in percent: 61
"""


class OctofanCli:
    def __init__(self, binary: str | Path = "/opt/octofan/fan_controller_cli", timeout: float = 5.0) -> None:
        self.binary = str(binary)
        self.timeout = timeout
        self.mock = os.getenv("OCTOFAN_MOCK", "0") == "1"
        self._lock = Lock()

    def status(self) -> ControllerStatus:
        if self.mock:
            return parse_controller_output(MOCK_OUTPUT)
        try:
            with self._lock:
                raw = subprocess.check_output([self.binary, "-r"], text=True, stderr=subprocess.STDOUT, timeout=self.timeout)
            return parse_controller_output(raw)
        except Exception as exc:
            return ControllerStatus(ok=False, error=str(exc))

    def set_fan_pwm(self, fan_id: int, pwm: int) -> None:
        self._run("-f", str(fan_id), "-v", str(max(0, min(255, pwm))))

    def set_all_fans_percent(self, fan_ids: list[int], percent: int) -> None:
        pwm = percent_to_pwm(percent)
        for fan_id in fan_ids:
            self.set_fan_pwm(fan_id, pwm)

    def set_fan_max_rpm(self, fan_id: int, rpm: int) -> None:
        self._run("-m", str(fan_id), "-v", str(max(0, min(65535, rpm))))

    def set_led(self, led_id: int, mode: int) -> None:
        self._run("-l", str(led_id), "-v", str(mode))

    def oled_text(self, x: int, y: int, flag: int, text: str) -> None:
        self._run("-o", f"{x},{y},{flag}", "-v", text[:20])

    def configure_watchdog(self, short_timeout: int, long_timeout: int) -> None:
        self._run("-w", str(short_timeout), "-v", str(long_timeout))

    def feed_watchdog(self) -> None:
        self._run("-s")

    def reset_rig(self) -> None:
        self._run("-x")

    def power_down(self) -> None:
        self._run("-p")

    def _run(self, *args: str) -> None:
        if self.mock:
            return
        with self._lock:
            subprocess.run([self.binary, *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=self.timeout, check=True)


def percent_to_pwm(percent: int) -> int:
    return max(0, min(255, round(255 * max(0, min(100, percent)) / 100)))
