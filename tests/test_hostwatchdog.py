import asyncio
import os
import struct

os.environ["OCTOFAN_CONFIG"] = "/tmp/octofan-test.yaml"
os.environ["OCTOFAN_MOCK"] = "1"

import pytest

from octofan_controller import app, hostwatchdog
from octofan_controller.config import WatchdogConfig
from octofan_controller.hostwatchdog import HostWatchdog


@pytest.fixture
def fake_ioctl(monkeypatch):
    calls = []

    def ioctl(fd, request, arg):
        calls.append(request)
        assert request == hostwatchdog.WDIOC_SETTIMEOUT
        return arg  # the driver echoes the timeout it accepted

    monkeypatch.setattr(hostwatchdog.fcntl, "ioctl", ioctl)
    return calls


@pytest.fixture(autouse=True)
def clean_state():
    app.state["host_watchdog"] = None
    app.state["host_watchdog_error"] = None
    app.state["events"] = []
    yield
    host = app.state["host_watchdog"]
    if host is not None and host.armed:
        host.disarm()
    app.state["host_watchdog"] = None


def test_feed_writes_and_clean_disarm_sends_magic_close(tmp_path, fake_ioctl):
    dev = tmp_path / "watchdog"
    dev.write_bytes(b"")
    wd = HostWatchdog(str(dev), 180)
    wd.open()
    assert wd.armed and wd.timeout == 180
    wd.feed()
    wd.feed()
    wd.disarm()
    assert not wd.armed
    assert dev.read_bytes() == b"\0\0V"


def test_refuses_to_run_on_driver_default_timeout(tmp_path, monkeypatch):
    def ioctl(fd, request, arg):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(hostwatchdog.fcntl, "ioctl", ioctl)
    dev = tmp_path / "watchdog"
    dev.write_bytes(b"")
    wd = HostWatchdog(str(dev), 180)
    with pytest.raises(OSError):
        wd.open()
    assert not wd.armed
    assert dev.read_bytes() == b"V"  # stopped with magic close, not left running


def test_feed_without_open_raises(tmp_path):
    with pytest.raises(OSError):
        HostWatchdog(str(tmp_path / "watchdog"), 180).feed()


def test_sync_arms_and_disarms_with_config(tmp_path, fake_ioctl):
    dev = tmp_path / "watchdog"
    dev.write_bytes(b"")
    cfg = WatchdogConfig(enabled=True, host_device=str(dev), host_timeout_seconds=120)
    app._sync_host_watchdog(cfg)
    host = app.state["host_watchdog"]
    assert host is not None and host.armed and host.timeout == 120
    assert app._host_watchdog_status() == {"armed": True, "device": str(dev), "timeout_seconds": 120}

    app._sync_host_watchdog(cfg)  # unchanged config keeps the same fd
    assert app.state["host_watchdog"] is host

    app._sync_host_watchdog(WatchdogConfig(enabled=True, host_device=None))
    assert app.state["host_watchdog"] is None
    assert dev.read_bytes() == b"V"


def test_sync_disarms_when_policy_and_keepalive_are_off(tmp_path, fake_ioctl):
    dev = tmp_path / "watchdog"
    dev.write_bytes(b"")
    app._sync_host_watchdog(WatchdogConfig(enabled=True, host_device=str(dev)))
    app._sync_host_watchdog(WatchdogConfig(enabled=False, keepalive_when_disabled=False, host_device=str(dev)))
    assert app.state["host_watchdog"] is None


def test_sync_reports_missing_device_once(tmp_path):
    cfg = WatchdogConfig(enabled=True, host_device=str(tmp_path / "missing"))
    app._sync_host_watchdog(cfg)
    app._sync_host_watchdog(cfg)
    assert app.state["host_watchdog"] is None
    assert len([e for e in app.state["events"] if "cannot arm host watchdog" in e]) == 1
    assert app._host_watchdog_status()["armed"] is False


def test_host_watchdog_is_fed_even_if_firmware_feed_fails(tmp_path, fake_ioctl, monkeypatch):
    dev = tmp_path / "watchdog"
    dev.write_bytes(b"")
    app._sync_host_watchdog(WatchdogConfig(enabled=True, host_device=str(dev)))

    def broken_feed():
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(app.cli, "feed_watchdog", broken_feed)
    asyncio.run(app._feed_watchdogs("failed to feed watchdog"))
    assert dev.read_bytes() == b"\0"
    assert any("Input/output error" in e for e in app.state["events"])
