import os
import asyncio

os.environ["OCTOFAN_CONFIG"] = "/tmp/octofan-test.yaml"
os.environ["OCTOFAN_MOCK"] = "1"

from octofan_controller.app import (
    ManualFanRequest,
    WatchdogMaintenanceRequest,
    _ai_recovery_decision,
    _ai_watchdog_down,
    _desired_led_modes,
    _gpu_idle_stop_candidate,
    _gpu_recovery_state,
    _watchdog_in_grace_period,
    _watchdog_maintenance_seconds_left,
    _watchdog_needs_rearm,
    _watchdog_startup_grace_active,
    api_fans_manual,
    api_watchdog_maintenance,
    serialize_status,
    state,
)
from octofan_controller.config import AppConfig, WatchdogConfig, load_config
from octofan_controller.control import FanControlDecision
from octofan_controller.flux import FluxStatus
from octofan_controller.llamacpp import LlamaCppServerStatus, LlamaCppStatus
from octofan_controller.ollama import OllamaStatus
from octofan_controller.metrics import metrics_payload, update_metrics
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.parser import BmeStatus, ControllerStatus
from octofan_controller.strata import StrataStatus


def test_status_and_metrics():
    status = serialize_status()
    assert "controller" in status
    assert "strata" in status
    assert "flux" in status
    assert "ai_recovery" in status
    metrics = metrics_payload().decode()
    assert "octofan_controller_up" in metrics
    assert "octofan_nvidia_smi_up" in metrics


def test_manual_fan_endpoint_forces_apply():
    cfg = AppConfig()
    cfg.fans.min_percent = 10
    cfg.fans.max_percent = 100
    state["config"] = cfg
    state["status"] = ControllerStatus()
    state["applied_fan_target"] = None
    state["applied_fan_ids"] = []

    response = asyncio.run(api_fans_manual(ManualFanRequest(percent=5)))

    assert response["percent"] == 10


def test_load_config_migrates_enabled_ollama_to_llamacpp(tmp_path):
    path = tmp_path / "octofan.yaml"
    path.write_text("ollama:\n  enabled: true\n", encoding="utf-8")

    cfg = load_config(path)

    assert cfg.llamacpp.enabled
    assert len(cfg.llamacpp.servers) == 1
    assert cfg.llamacpp.servers[0].name == "llama3.1:8b"


def test_gpu_idle_stop_candidate_requires_cool_idle_gpus():
    cfg = AppConfig()
    cfg.fans.mode = "auto"
    cfg.fans.gpu_idle_stop_enabled = True
    status = ControllerStatus()
    status.bme280[0] = BmeStatus(id=0, temp_c=30)
    nvidia = NvidiaStatus(
        ok=True,
        gpus=[
            GpuStatus(
                index=0,
                uuid="gpu-0",
                name="test",
                pci_bus_id="00000000:02:00.0",
                temperature_gpu_c=35,
                utilization_gpu_percent=0,
                power_draw_watts=10,
                encoder_sessions=0,
                decoder_sessions=0,
            )
        ],
    )

    assert _gpu_idle_stop_candidate(cfg, status, nvidia, False)


def test_gpu_idle_stop_candidate_rejects_gpu_load():
    cfg = AppConfig()
    cfg.fans.mode = "auto"
    cfg.fans.gpu_idle_stop_enabled = True
    status = ControllerStatus()
    status.bme280[0] = BmeStatus(id=0, temp_c=30)
    nvidia = NvidiaStatus(
        ok=True,
        gpus=[
            GpuStatus(
                index=0,
                uuid="gpu-0",
                name="test",
                pci_bus_id="00000000:02:00.0",
                temperature_gpu_c=35,
                utilization_gpu_percent=80,
                power_draw_watts=80,
            )
        ],
    )

    assert not _gpu_idle_stop_candidate(cfg, status, nvidia, False)


def test_led_modes_show_online_and_gpu_activity():
    cfg = AppConfig()
    cfg.leds.enabled = True
    status = ControllerStatus()
    nvidia = NvidiaStatus(
        ok=True,
        gpus=[
            GpuStatus(
                index=0,
                uuid="gpu-0",
                name="test",
                pci_bus_id="00000000:02:00.0",
                utilization_gpu_percent=80,
                power_draw_watts=80,
            )
        ],
    )

    modes = _desired_led_modes(cfg, status, LlamaCppStatus(ok=True), OllamaStatus(), StrataStatus(), nvidia)

    assert modes == {
        cfg.leds.warning_led_id: cfg.leds.off_mode,
        cfg.leds.online_led_id: cfg.leds.on_mode,
        cfg.leds.activity_led_id: cfg.leds.fast_blink_mode,
    }


def test_led_modes_warn_when_llamacpp_is_down():
    cfg = AppConfig()
    cfg.leds.enabled = True
    cfg.llamacpp.enabled = True
    status = ControllerStatus()
    nvidia = NvidiaStatus(ok=True, gpus=[])

    modes = _desired_led_modes(cfg, status, LlamaCppStatus(ok=False), OllamaStatus(), StrataStatus(), nvidia)

    assert modes[cfg.leds.warning_led_id] == cfg.leds.slow_blink_mode
    assert modes[cfg.leds.online_led_id] == cfg.leds.off_mode
    assert modes[cfg.leds.activity_led_id] == cfg.leds.off_mode


def test_led_modes_show_controller_online_when_llamacpp_is_disabled():
    cfg = AppConfig()
    cfg.leds.enabled = True
    cfg.llamacpp.enabled = False

    modes = _desired_led_modes(
        cfg,
        ControllerStatus(ok=True),
        LlamaCppStatus(ok=False),
        OllamaStatus(),
        StrataStatus(),
        NvidiaStatus(ok=True, gpus=[]),
    )

    assert modes[cfg.leds.warning_led_id] == cfg.leds.off_mode
    assert modes[cfg.leds.online_led_id] == cfg.leds.on_mode
    assert modes[cfg.leds.activity_led_id] == cfg.leds.off_mode


def test_led_modes_warn_when_strata_is_down():
    cfg = AppConfig()
    cfg.leds.enabled = True
    cfg.strata.enabled = True

    modes = _desired_led_modes(
        cfg,
        ControllerStatus(ok=True),
        LlamaCppStatus(),
        OllamaStatus(),
        StrataStatus(enabled=True, up=False),
        NvidiaStatus(ok=True, gpus=[]),
    )

    assert modes[cfg.leds.warning_led_id] == cfg.leds.slow_blink_mode
    assert modes[cfg.leds.online_led_id] == cfg.leds.off_mode


def test_ai_watchdog_down_names_enabled_failing_backend():
    cfg = AppConfig()
    cfg.strata.enabled = True

    assert _ai_watchdog_down(cfg, OllamaStatus(), StrataStatus(enabled=True, up=True)) is None
    assert _ai_watchdog_down(cfg, OllamaStatus(), StrataStatus(enabled=True, base_url="http://strata:8080", up=False)) == "strata"
    assert _ai_watchdog_down(cfg, OllamaStatus(), StrataStatus(enabled=True, up=False)) is None
    cfg.strata.enabled = False
    cfg.ollama.enabled = True
    assert _ai_watchdog_down(cfg, OllamaStatus(enabled=True, base_url="http://ollama:11434", up=False), StrataStatus()) == "ollama"
    assert _ai_watchdog_down(cfg, OllamaStatus(enabled=True, up=True), StrataStatus()) is None


def test_ai_recovery_decision_restarts_after_threshold_and_cooldowns():
    cfg = WatchdogConfig(
        ai_recovery_enabled=True,
        ai_recovery_min_failures=3,
        ai_recovery_cooldown_seconds=900,
        ai_recovery_restart_containers=["strata-qwen"],
    )

    failures, cooldown, restart, note = _ai_recovery_decision("strata", False, 0, None, now=1000.0, cfg=cfg)
    assert failures == 1 and cooldown is None and not restart and "1/3" in note

    failures, cooldown, restart, note = _ai_recovery_decision("strata", False, failures, cooldown, now=1030.0, cfg=cfg)
    assert failures == 2 and not restart

    failures, cooldown, restart, note = _ai_recovery_decision("strata", False, failures, cooldown, now=1060.0, cfg=cfg)
    assert failures == 0 and cooldown == 1960.0 and restart and "strata-qwen" in note

    failures, cooldown, restart, note = _ai_recovery_decision("strata", False, 0, cooldown, now=1200.0, cfg=cfg)
    assert failures == 0 and not restart and "cooldown" in note

    failures, cooldown, restart, note = _ai_recovery_decision(None, False, 2, cooldown, now=1230.0, cfg=cfg)
    assert failures == 0 and cooldown == 1960.0 and not restart and note is None


def test_ai_recovery_decision_waits_while_docker_health_is_starting():
    cfg = WatchdogConfig(ai_recovery_enabled=True, ai_recovery_min_failures=1, ai_recovery_restart_containers=["strata-qwen"])

    failures, cooldown, restart, note = _ai_recovery_decision("strata", True, 2, None, now=1000.0, cfg=cfg)
    assert failures == 0 and not restart and note is None


def test_ai_recovery_decision_without_config_only_reports():
    cfg = WatchdogConfig(ai_recovery_enabled=False, ai_recovery_restart_containers=[])

    failures, cooldown, restart, note = _ai_recovery_decision("strata", False, 1, None, now=1000.0, cfg=cfg)
    assert failures == 2 and not restart and note == "AI down: strata"


def test_watchdog_tolerates_transient_unhealthy_checks():
    assert _watchdog_in_grace_period(unhealthy_failures=1, threshold=3)
    assert _watchdog_in_grace_period(unhealthy_failures=2, threshold=3)
    assert not _watchdog_in_grace_period(unhealthy_failures=3, threshold=3)


def test_watchdog_rearms_when_firmware_reports_disarmed():
    armed = ControllerStatus(ok=True, watchdog_mode=2)
    disarmed = ControllerStatus(ok=True, watchdog_mode=0)
    unknown = ControllerStatus(ok=True)
    offline = ControllerStatus(ok=False, error="usb gone")
    assert _watchdog_needs_rearm(configured=True, status=disarmed)
    assert _watchdog_needs_rearm(configured=True, status=unknown)
    assert not _watchdog_needs_rearm(configured=True, status=armed)
    assert not _watchdog_needs_rearm(configured=False, status=disarmed)
    assert not _watchdog_needs_rearm(configured=True, status=offline)


def test_gpu_recovery_state_grace_window_before_reset():
    cfg = WatchdogConfig(gpus_expected=4, gpu_recovery_enabled=True, gpu_recovery_grace_seconds=300)
    errors = ["expected 4 GPUs, nvidia-smi reports 3"]

    blocking, deadline, run_recovery, note = _gpu_recovery_state(errors, None, now=1000.0, cfg=cfg)
    assert not blocking and run_recovery and deadline == 1300.0

    blocking, deadline, run_recovery, note = _gpu_recovery_state(errors, deadline, now=1150.0, cfg=cfg)
    assert not blocking and not run_recovery and note == "GPU recovery in progress"

    blocking, deadline, run_recovery, note = _gpu_recovery_state(errors, deadline, now=1301.0, cfg=cfg)
    assert blocking and deadline == 1300.0 and not run_recovery and note == "GPU recovery exhausted"

    blocking, deadline, run_recovery, note = _gpu_recovery_state(errors, deadline, now=1331.0, cfg=cfg)
    assert blocking and deadline == 1300.0 and not run_recovery and note == "GPU recovery exhausted"

    blocking, deadline, _, _ = _gpu_recovery_state([], deadline, now=1400.0, cfg=cfg)
    assert not blocking and deadline is None


def test_gpu_recovery_state_disabled_blocks_immediately():
    cfg = WatchdogConfig(gpus_expected=4, gpu_recovery_enabled=False)
    blocking, deadline, run_recovery, _ = _gpu_recovery_state(["boom"], None, now=1000.0, cfg=cfg)
    assert blocking and deadline is None and not run_recovery


def test_watchdog_maintenance_endpoint_set_and_clear():
    asyncio.run(api_watchdog_maintenance(WatchdogMaintenanceRequest(minutes=10)))
    assert _watchdog_maintenance_seconds_left() > 500
    asyncio.run(api_watchdog_maintenance(WatchdogMaintenanceRequest(minutes=0)))
    assert _watchdog_maintenance_seconds_left() == 0


def test_watchdog_startup_grace_only_at_loop_start():
    assert _watchdog_startup_grace_active(loop_started=1000.0, now=1030.0)
    assert not _watchdog_startup_grace_active(loop_started=1000.0, now=1121.0)


def test_metrics_exports_llamacpp_server_status():
    llamacpp = LlamaCppStatus(
        ok=True,
        available_models=1,
        servers=[
            LlamaCppServerStatus(
                name="qwen3coder:30b",
                gpu="0",
                ok=True,
                model="qwen3coder:30b",
                total_slots=2,
                processing_slots=1,
            )
        ],
    )
    fan_control = FanControlDecision(
        target_percent=18,
        raw_target_percent=64,
        reason="gpu",
        temperature_delta_c=5,
        intake_target_percent=10,
        exhaust_target_percent=30,
        delta_target_percent=20,
        gpu_target_percent=64,
    )
    update_metrics(ControllerStatus(), llamacpp, 18, fan_control=fan_control)

    metrics = metrics_payload().decode()

    assert 'octofan_ai_available_models{source="llamacpp"}' in metrics
    assert 'octofan_llamacpp_up{gpu="0",model="qwen3coder:30b",name="qwen3coder:30b"}' in metrics
    assert 'octofan_fan_control_target_percent{source="gpu"} 64.0' in metrics
    assert 'octofan_fan_control_target_percent{source="combined"} 64.0' in metrics
    assert "octofan_temperature_delta_celsius 5.0" in metrics


def test_metrics_exports_strata_and_flux_health():
    update_metrics(
        ControllerStatus(),
        LlamaCppStatus(),
        10,
        strata=StrataStatus(enabled=True, up=True, total_models=1, loaded_models=1),
        ollama=OllamaStatus(),
        flux=FluxStatus(enabled=True, up=False, error="HTTP 503"),
    )

    metrics = metrics_payload().decode()

    assert 'octofan_ai_up{source="strata"} 1.0' in metrics
    assert 'octofan_ai_available_models{source="strata"} 1.0' in metrics
    assert 'octofan_ai_running_models{source="strata"} 1.0' in metrics
    assert 'octofan_flux_up{source="flux"} 0.0' in metrics
    assert 'source="ollama"' not in metrics


def test_metrics_drop_sources_when_backends_are_disabled():
    update_metrics(
        ControllerStatus(),
        LlamaCppStatus(),
        10,
        strata=StrataStatus(),
        flux=FluxStatus(),
    )

    metrics = metrics_payload().decode()

    assert 'source="strata"' not in metrics
    assert 'source="flux"' not in metrics
