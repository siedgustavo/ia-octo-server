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


def test_docker_container_health_reads_state():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/containers/strata-qwen/json"
        # Real Docker Engine payload shape (capitalized "Status").
        return httpx.Response(200, json={"State": {"Health": {"Status": "starting", "FailingStreak": 0}}})

    client = DockerApiClient(transport=httpx.MockTransport(handler))
    assert client.container_health("strata-qwen") == "starting"


def test_docker_container_health_missing_container_is_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = DockerApiClient(transport=httpx.MockTransport(handler))
    assert client.container_health("nope") is None


def test_disk_check_writes_and_fsyncs_heartbeat(tmp_path):
    target = tmp_path / "heartbeat"
    ok, error = asyncio.run(_run_check(WatchdogCheck(type="disk", target=str(target), timeout_seconds=5)))
    assert ok and error is None
    assert float(target.read_text())


def test_disk_check_reports_io_error(tmp_path):
    target = tmp_path / "missing-dir" / "heartbeat"
    ok, error = asyncio.run(_run_check(WatchdogCheck(type="disk", target=str(target), timeout_seconds=5)))
    assert not ok
    assert "No such file" in error


def test_disk_check_hung_write_fails_without_piling_threads(monkeypatch, tmp_path):
    import threading

    from octofan_controller import watchdog

    release = threading.Event()
    calls = []

    def stuck(path):
        calls.append(path)
        release.wait(10)

    monkeypatch.setattr(watchdog, "_write_heartbeat", stuck)
    check = WatchdogCheck(type="disk", target=str(tmp_path / "hb"), timeout_seconds=0.2)

    async def scenario():
        first = await _run_check(check)
        second = await _run_check(check)
        release.set()
        await asyncio.sleep(0.1)
        third = await _run_check(check)
        return first, second, third

    try:
        first, second, third = asyncio.run(scenario())
    finally:
        release.set()
        watchdog._disk_probes.clear()
    assert not first[0] and "exceeded" in first[1]
    assert not second[0] and "still blocked" in second[1]
    assert third == (True, None)
    assert len(calls) == 2  # the second check did not spawn another writer


def test_ssh_timeout_error_names_the_failure(monkeypatch):
    async def never(host, port):
        await asyncio.sleep(10)

    monkeypatch.setattr("asyncio.open_connection", never)
    ok, error = asyncio.run(_run_check(WatchdogCheck(type="ssh", target="host:22", timeout_seconds=0.1)))
    assert not ok
    assert error == "ssh:host:22 connect TimeoutError"


def test_docker_container_running_reads_state():
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.split("/")[2]
        if name == "gone":
            return httpx.Response(404)
        return httpx.Response(200, json={"State": {"Running": name == "strata-qwen"}})

    client = DockerApiClient(transport=httpx.MockTransport(handler))
    assert client.container_running("strata-qwen") is True
    assert client.container_running("maya-deepseek") is False
    assert client.container_running("gone") is False


def test_restart_containers_skips_stopped_backends(monkeypatch):
    from octofan_controller import app as app_module

    restarted = []
    monkeypatch.setattr(app_module.docker_client, "container_running", lambda name: name == "strata-qwen")
    monkeypatch.setattr(app_module.docker_client, "restart_container", lambda name: restarted.append(name) or True)
    events = []
    monkeypatch.setattr(app_module, "_event", events.append)

    asyncio.run(app_module._restart_containers(["strata-qwen", "maya-deepseek"], "AI watchdog"))
    assert restarted == ["strata-qwen"]

    restarted.clear()
    monkeypatch.setattr(app_module.docker_client, "container_running", lambda name: False)
    asyncio.run(app_module._restart_containers(["strata-qwen", "maya-deepseek"], "AI watchdog"))
    assert restarted == []
    assert "nothing restarted" in events[-1]
