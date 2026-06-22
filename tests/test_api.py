import os
import asyncio

os.environ["OCTOFAN_CONFIG"] = "/tmp/octofan-test.yaml"
os.environ["OCTOFAN_MOCK"] = "1"

from octofan_controller.app import ManualFanRequest, _desired_led_modes, _gpu_idle_stop_candidate, api_fans_manual, serialize_status, state
from octofan_controller.config import AppConfig
from octofan_controller.metrics import metrics_payload
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.ai_runtime import AIStatus
from octofan_controller.parser import BmeStatus, ControllerStatus


def test_status_and_metrics():
    status = serialize_status()
    assert "controller" in status
    assert "ai" in status
    assert status["ollama"] == status["ai"]
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

    assert _gpu_idle_stop_candidate(cfg, status, nvidia, AIStatus(generating=False))


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

    assert not _gpu_idle_stop_candidate(cfg, status, nvidia, AIStatus(generating=False))


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

    modes = _desired_led_modes(cfg, status, AIStatus(ok=True), nvidia)

    assert modes == {
        cfg.leds.warning_led_id: cfg.leds.off_mode,
        cfg.leds.online_led_id: cfg.leds.on_mode,
        cfg.leds.activity_led_id: cfg.leds.fast_blink_mode,
    }


def test_led_modes_warn_when_ai_runtime_is_down():
    cfg = AppConfig()
    cfg.leds.enabled = True
    cfg.ai.enabled = True
    status = ControllerStatus()
    nvidia = NvidiaStatus(ok=True, gpus=[])

    modes = _desired_led_modes(cfg, status, AIStatus(ok=False), nvidia)

    assert modes[cfg.leds.warning_led_id] == cfg.leds.slow_blink_mode
    assert modes[cfg.leds.online_led_id] == cfg.leds.off_mode
    assert modes[cfg.leds.activity_led_id] == cfg.leds.off_mode
