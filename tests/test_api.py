import os

os.environ["OCTOFAN_CONFIG"] = "/tmp/octofan-test.yaml"
os.environ["OCTOFAN_MOCK"] = "1"

from fastapi.testclient import TestClient

from octofan_controller.app import _gpu_idle_stop_candidate, app
from octofan_controller.config import AppConfig
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.ollama import OllamaStatus
from octofan_controller.parser import BmeStatus, ControllerStatus


def test_status_and_metrics():
    with TestClient(app) as client:
        status = client.get("/api/status")
        assert status.status_code == 200
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "octofan_controller_up" in metrics.text
        assert "octofan_nvidia_smi_up" in metrics.text


def test_manual_fan_endpoint_forces_apply():
    with TestClient(app) as client:
        response = client.post("/api/fans/manual", json={"percent": 10})
        assert response.status_code == 200
        assert response.json()["percent"] == 10


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

    assert _gpu_idle_stop_candidate(cfg, status, nvidia, OllamaStatus(generating=False))


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

    assert not _gpu_idle_stop_candidate(cfg, status, nvidia, OllamaStatus(generating=False))
