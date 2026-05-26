from octofan_controller.config import FanConfig
from octofan_controller.control import calculate_target_fan_percent
from octofan_controller.parser import BmeStatus, ControllerStatus


def status_with_temp(temp):
    status = ControllerStatus()
    status.bme280[0] = BmeStatus(id=0, temp_c=temp)
    return status


def test_below_target_moves_toward_min():
    cfg = FanConfig(target_temp_c=40, min_percent=30, max_percent=100, max_step_percent=10)
    assert calculate_target_fan_percent(status_with_temp(34), cfg, 60) == 50


def test_above_target_steps_up():
    cfg = FanConfig(target_temp_c=38, min_percent=35, max_percent=100, max_step_percent=8)
    assert calculate_target_fan_percent(status_with_temp(46), cfg, 40) == 48


def test_fail_safe_on_bad_read():
    cfg = FanConfig(fail_safe_percent=100)
    assert calculate_target_fan_percent(ControllerStatus(ok=False), cfg, 35) == 100


def test_manual_mode_ignores_transient_bad_read():
    cfg = FanConfig(mode="manual", min_percent=10, manual_percent=10, fail_safe_percent=100)
    assert calculate_target_fan_percent(ControllerStatus(ok=False), cfg, 35) == 10


def test_manual_mode():
    cfg = FanConfig(mode="manual", manual_percent=72)
    assert calculate_target_fan_percent(status_with_temp(80), cfg, 35) == 72


def test_manual_mode_clamps_to_active_range():
    cfg = FanConfig(mode="manual", min_percent=10, max_percent=80, manual_percent=5)
    assert calculate_target_fan_percent(status_with_temp(30), cfg, 35) == 10


def test_gpu_idle_stop_stays_inside_active_range():
    cfg = FanConfig(gpu_idle_stop_enabled=True, min_percent=10, gpu_idle_stop_percent=0)
    assert calculate_target_fan_percent(status_with_temp(30), cfg, 35, gpu_idle_stop_active=True) == 10


def test_gpu_idle_stop_does_not_override_manual_mode():
    cfg = FanConfig(mode="manual", min_percent=10, manual_percent=10, gpu_idle_stop_enabled=True, gpu_idle_stop_percent=0)
    assert calculate_target_fan_percent(status_with_temp(30), cfg, 35, gpu_idle_stop_active=True) == 10
