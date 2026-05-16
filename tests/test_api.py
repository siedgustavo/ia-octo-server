import os

os.environ["OCTOFAN_CONFIG"] = "/tmp/octofan-test.yaml"
os.environ["OCTOFAN_MOCK"] = "1"

from fastapi.testclient import TestClient

from octofan_controller.app import app


def test_status_and_metrics():
    with TestClient(app) as client:
        status = client.get("/api/status")
        assert status.status_code == 200
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "octofan_controller_up" in metrics.text
        assert "octofan_nvidia_smi_up" in metrics.text
