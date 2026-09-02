from octofan_controller.cli import MOCK_OUTPUT
from octofan_controller.parser import parse_controller_output


def test_parse_controller_output():
    status = parse_controller_output(MOCK_OUTPUT)
    assert status.ok
    assert status.serial == "0x0102030405060708090A"
    assert status.version_fw == 3.0
    assert status.intake_temp_c == 32.5
    assert status.exhaust_temp_c == 40.2
    assert status.fans[0].rpm == 3100
    assert status.fans[0].percent == 61
    assert status.psus[0].power_ac == 692.0
    assert status.power_ac_total_w == 692.0


def test_parse_controller_output_with_psu_peaks_and_energy():
    raw = """PSMI(DPS1200-compat.) PSU No. 0 Peak Pac: 124.0
PSMI(DPS1200-compat.) PSU No. 0 Peak Idc: 6.5
PSMI(DPS1200-compat.) PSU No. 0 Wac: 0.567
"""
    status = parse_controller_output(raw)
    assert status.psus[0].peak_power_ac == 124.0
    assert status.psus[0].peak_amperage_dc == 6.5
    assert status.psus[0].energy_ac_kwh == 0.567


def test_intake_temp_ignores_impossible_sensor_values():
    raw = """Temperature No. 0 Celsius: -60
Temperature No. 1 Celsius: 22
Temperature No. 2 Celsius: 281
BME280 No. 0 Temp: 188.83
"""
    status = parse_controller_output(raw)
    assert status.intake_temp_c == 22
    assert status.exhaust_temp_c == 22


def test_parse_real_firmware_watchdog_lines():
    raw = """Watchdog Mode: 2
Watchdog short timout: 120
Watchdog long timeout: 732
Watchdog Resets: 19
"""
    status = parse_controller_output(raw)
    assert status.watchdog_mode == 2
    assert status.watchdog_short_timeout == 120
    assert status.watchdog_long_timeout == 732
    assert status.watchdog_resets == 19
