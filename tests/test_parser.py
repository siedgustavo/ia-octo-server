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
