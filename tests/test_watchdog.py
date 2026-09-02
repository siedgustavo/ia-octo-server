import asyncio

import httpx

from octofan_controller.config import WatchdogCheck, WatchdogConfig
from octofan_controller.docker import DockerApiClient
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.watchdog import _run_check, gpu_watchdog_errors


def _gpus(count: int, phantoms: int = 0) -> list[GpuStatus]:
    gpus = [GpuStatus(index=i, uuid=f"GPU-{i}", name="RTX", pci_bus_id=f"0{i}:00.0") for i in range(count)]
    gpus += [GpuStatus(index=count + i, uuid="", name="", pci_bus_id="") for i in range(phantoms)]
    return gpus


def test_gpu_watchdog_disabled_when_not_expected():
    assert gpu_watchdog_errors(NvidiaStatus(ok=False, gpus=[], error="boom"), 0) == []


def test_gpu_watchdog_ok_with_expected_count():
    assert gpu_watchdog_errors(NvidiaStatus(ok=True, gpus=_gpus(4)), 4) == []


def test_gpu_watchdog_detects_lost_gpu():
    errors = gpu_watchdog_errors(NvidiaStatus(ok=True, gpus=_gpus(3)), 4)
    assert errors == ["expected 4 GPUs, nvidia-smi reports 3"]


def test_gpu_watchdog_detects_phantom_entry():
    nvidia = NvidiaStatus(ok=True, gpus=_gpus(4, phantoms=1))
    errors = gpu_watchdog_errors(nvidia, 4)
    assert any("without UUID" in e for e in errors)


def test_gpu_watchdog_detects_nvidia_smi_failure():
    nvidia = NvidiaStatus(ok=False, gpus=[], error="timeout")
    assert gpu_watchdog_errors(nvidia, 4) == ["nvidia-smi failed: timeout"]


class _FakeWriter:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


def _fake_open(banner: bytes):
    class _Reader:
        async def readuntil(self, sep):
            return banner

    async def open_connection(host, port):
        return _Reader(), _FakeWriter()

    return open_connection


def test_ssh_check_accepts_valid_banner(monkeypatch):
    monkeypatch.setattr("asyncio.open_connection", _fake_open(b"SSH-2.0-OpenSSH_9.6\r\n"))
    ok, error = asyncio.run(_run_check(WatchdogCheck(type="ssh", target="host:22")))
    assert ok
    assert error is None


def test_ssh_check_rejects_zombie_banner(monkeypatch):
    monkeypatch.setattr("asyncio.open_connection", _fake_open(b"GARBAGE\r\n"))
    ok, error = asyncio.run(_run_check(WatchdogCheck(type="ssh", target="host:22")))
    assert not ok
    assert "unexpected ssh banner" in error


def test_docker_restart_container_uses_socket_api():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(204)

    client = DockerApiClient(transport=httpx.MockTransport(handler))
    assert client.restart_container("octofan-ollama")
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/containers/octofan-ollama/restart?t=10")


def test_docker_restart_container_reports_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = DockerApiClient(transport=httpx.MockTransport(handler))
    assert not client.restart_container("nope")
