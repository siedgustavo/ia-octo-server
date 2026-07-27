import os
import asyncio

os.environ["OCTOFAN_CONFIG"] = "/tmp/octofan-test.yaml"
os.environ["OCTOFAN_MOCK"] = "1"

from octofan_controller.app import (
    ManualFanRequest,
    _desired_led_modes,
    _gpu_idle_stop_candidate,
    _watchdog_in_grace_period,
    api_fans_manual,
    serialize_status,
    state,
)
from octofan_controller.config import AppConfig, load_config
from octofan_controller.llamacpp import LlamaCppServerStatus, LlamaCppStatus
from octofan_controller.metrics import metrics_payload, update_metrics
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.parser import BmeStatus, ControllerStatus


def test_status_and_metrics():
    status = serialize_status()
    assert "controller" in status
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
    assert len(cfg.llamacpp.servers) == 2


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

    assert _gpu_idle_stop_candidate(cfg, status, nvidia, LlamaCppStatus(generating=False))


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

    assert not _gpu_idle_stop_candidate(cfg, status, nvidia, LlamaCppStatus(generating=False))


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

    modes = _desired_led_modes(cfg, status, LlamaCppStatus(ok=True), nvidia)

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

    modes = _desired_led_modes(cfg, status, LlamaCppStatus(ok=False), nvidia)

    assert modes[cfg.leds.warning_led_id] == cfg.leds.slow_blink_mode
    assert modes[cfg.leds.online_led_id] == cfg.leds.off_mode
    assert modes[cfg.leds.activity_led_id] == cfg.leds.off_mode


def test_watchdog_tolerates_transient_unhealthy_checks():
    assert _watchdog_in_grace_period(unhealthy_failures=1, threshold=3)
    assert _watchdog_in_grace_period(unhealthy_failures=2, threshold=3)
    assert not _watchdog_in_grace_period(unhealthy_failures=3, threshold=3)


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
    update_metrics(ControllerStatus(), llamacpp, None)

    metrics = metrics_payload().decode()

    assert 'octofan_ai_available_models{source="llamacpp"}' in metrics
    assert 'octofan_llamacpp_up{gpu="0",model="qwen3coder:30b",name="qwen3coder:30b"}' in metrics
