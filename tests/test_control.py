from octofan_controller.config import FanConfig
from octofan_controller.control import (
    calculate_fan_control_decision,
    calculate_target_fan_percent,
)
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.parser import BmeStatus, ControllerStatus


def automatic_config(**overrides):
    return FanConfig(mode="auto", min_percent=10, max_percent=100, **overrides)


def status_with_temps(intake=22, exhaust=23):
    status = ControllerStatus()
    status.bme280[0] = BmeStatus(id=0, temp_c=intake)
    status.temperatures[1] = exhaust
    return status


def nvidia_with_temp(temp):
    return NvidiaStatus(
        ok=True,
        gpus=[
            GpuStatus(
                index=0,
                uuid="gpu-0",
                name="test",
                pci_bus_id="00000000:01:00.0",
                temperature_gpu_c=temp,
            )
        ],
    )


def test_cool_system_stays_at_quiet_minimum():
    decision = calculate_fan_control_decision(
        status_with_temps(), automatic_config(), 10, nvidia=nvidia_with_temp(35)
    )

    assert decision.target_percent == 10
    assert decision.raw_target_percent == 10
    assert decision.temperature_delta_c == 1
    assert decision.intake_target_percent == 10
    assert decision.exhaust_target_percent == 10
    assert decision.delta_target_percent == 10
    assert decision.gpu_target_percent == 10


def test_hottest_chassis_signal_wins_and_ramps_up():
    decision = calculate_fan_control_decision(
        status_with_temps(intake=35, exhaust=36),
        automatic_config(max_step_percent=8),
        20,
        nvidia=nvidia_with_temp(66),
    )

    assert decision.intake_target_percent == 55
    assert decision.exhaust_target_percent == 46
    assert decision.delta_target_percent == 10
    assert decision.gpu_target_percent == 10
    assert decision.raw_target_percent == 55
    assert decision.target_percent == 28
    assert decision.reason == "intake"


def test_normal_gpu_temperature_does_not_raise_chassis_fans():
    decision = calculate_fan_control_decision(
        status_with_temps(), automatic_config(), 10, nvidia=nvidia_with_temp(70)
    )

    assert decision.gpu_target_percent == 10
    assert decision.raw_target_percent == 10


def test_hot_gpu_assistance_is_capped_below_critical_temperature():
    cfg = automatic_config(gpu_curve_max_percent=40)
    warm = calculate_fan_control_decision(
        status_with_temps(), cfg, 10, nvidia=nvidia_with_temp(80)
    )
    hot = calculate_fan_control_decision(
        status_with_temps(), cfg, 10, nvidia=nvidia_with_temp(85)
    )

    assert warm.gpu_target_percent == 25
    assert hot.gpu_target_percent == 40
    assert hot.raw_target_percent == 40


def test_fans_ramp_down_more_slowly_than_they_ramp_up():
    cfg = automatic_config(max_step_percent=8, max_down_step_percent=4)

    assert calculate_target_fan_percent(status_with_temps(), cfg, 70) == 66


def test_small_target_changes_are_absorbed_by_deadband():
    cfg = automatic_config(target_deadband_percent=2)
    status = status_with_temps(intake=30.2, exhaust=23)

    assert calculate_target_fan_percent(status, cfg, 10) == 10


def test_critical_gpu_temperature_goes_immediately_to_full_speed():
    decision = calculate_fan_control_decision(
        status_with_temps(), automatic_config(), 10, nvidia=nvidia_with_temp(88)
    )

    assert decision.target_percent == 100
    assert decision.raw_target_percent == 100
    assert decision.reason == "critical_gpu"


def test_critical_exhaust_temperature_goes_immediately_to_full_speed():
    decision = calculate_fan_control_decision(
        status_with_temps(exhaust=50), automatic_config(), 10, nvidia=nvidia_with_temp(30)
    )

    assert decision.target_percent == 100
    assert decision.reason == "critical_exhaust"


def test_critical_intake_exhaust_delta_goes_immediately_to_full_speed():
    decision = calculate_fan_control_decision(
        status_with_temps(intake=18, exhaust=40),
        automatic_config(),
        10,
        nvidia=nvidia_with_temp(30),
    )

    assert decision.target_percent == 100
    assert decision.reason == "critical_delta"


def test_fail_safe_ramps_up_on_bad_controller_read():
    cfg = automatic_config(fail_safe_percent=100, max_step_percent=8)
    assert calculate_target_fan_percent(ControllerStatus(ok=False), cfg, 35) == 43


def test_fail_safe_can_still_jump_to_max_when_ramp_disabled():
    cfg = automatic_config(fail_safe_percent=100, fail_safe_ramp=False)
    assert calculate_target_fan_percent(ControllerStatus(ok=False), cfg, 35) == 100


def test_manual_mode_ignores_bad_read_and_gpu_temperature():
    cfg = FanConfig(mode="manual", min_percent=10, manual_percent=10, fail_safe_percent=100)
    decision = calculate_fan_control_decision(
        ControllerStatus(ok=False), cfg, 35, nvidia=nvidia_with_temp(90)
    )

    assert decision.target_percent == 10
    assert decision.reason == "manual"


def test_manual_mode_exposes_shadow_automatic_demand():
    cfg = FanConfig(mode="manual", min_percent=10, manual_percent=10)
    decision = calculate_fan_control_decision(
        status_with_temps(intake=30, exhaust=35), cfg, 10, nvidia=nvidia_with_temp(80)
    )

    assert decision.target_percent == 10
    assert decision.raw_target_percent == 40
    assert decision.exhaust_target_percent == 40
    assert decision.delta_target_percent == 10
    assert decision.gpu_target_percent == 25
    assert decision.reason == "manual"


def test_manual_mode_clamps_to_active_range():
    cfg = FanConfig(mode="manual", min_percent=10, max_percent=80, manual_percent=5)
    assert calculate_target_fan_percent(status_with_temps(), cfg, 35) == 10


def test_gpu_idle_stop_stays_inside_active_range():
    cfg = automatic_config(gpu_idle_stop_enabled=True, gpu_idle_stop_percent=0)
    decision = calculate_fan_control_decision(
        status_with_temps(), cfg, 35, gpu_idle_stop_active=True, nvidia=nvidia_with_temp(30)
    )

    assert decision.target_percent == 10
    assert decision.reason == "gpu_idle"


def test_gpu_idle_stop_does_not_override_manual_mode():
    cfg = FanConfig(
        mode="manual",
        min_percent=10,
        manual_percent=10,
        gpu_idle_stop_enabled=True,
        gpu_idle_stop_percent=0,
    )
    assert calculate_target_fan_percent(
        status_with_temps(), cfg, 35, gpu_idle_stop_active=True
    ) == 10
