from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import WatchdogCheck, WatchdogConfig
from .nvidia import NvidiaStatus


@dataclass
class WatchdogResult:
    healthy: bool
    checked: int
    errors: list[str]


def gpu_watchdog_errors(nvidia: NvidiaStatus, gpus_expected: int) -> list[str]:
    if gpus_expected <= 0:
        return []
    if not nvidia.ok:
        return [f"nvidia-smi failed: {nvidia.error or 'unknown error'}"]
    errors: list[str] = []
    phantoms = sum(1 for gpu in nvidia.gpus if not gpu.uuid)
    if phantoms:
        errors.append(f"nvidia-smi returned {phantoms} GPU entries without UUID")
    real = len(nvidia.gpus) - phantoms
    if real != gpus_expected:
        errors.append(f"expected {gpus_expected} GPUs, nvidia-smi reports {real}")
    return errors


async def run_watchdog_checks(cfg: WatchdogConfig) -> WatchdogResult:
    if not cfg.checks:
        return WatchdogResult(healthy=True, checked=0, errors=[])
    errors: list[str] = []
    for check in cfg.checks:
        ok, error = await _run_check(check)
        if not ok:
            errors.append(error or f"{check.type}:{check.target} failed")
    return WatchdogResult(healthy=not errors, checked=len(cfg.checks), errors=errors)


_disk_probes: dict[str, tuple[asyncio.Future, float]] = {}


def _write_heartbeat(path: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, f"{time.time():.3f}\n".encode())
        os.fsync(fd)
    finally:
        os.close(fd)


async def _run_disk_check(check: WatchdogCheck) -> tuple[bool, str | None]:
    """Write + fsync a heartbeat file on the host disk from a worker thread.

    A dead NVMe can leave the write stuck in D state forever. That thread is
    never awaited again: while it is pending, every later check fails at once
    instead of piling up more stuck threads.
    """
    pending = _disk_probes.get(check.target)
    if pending is not None:
        future, started = pending
        if not future.done():
            return False, f"disk:{check.target} previous write still blocked after {time.monotonic() - started:.0f}s"
        del _disk_probes[check.target]
    future = asyncio.ensure_future(asyncio.to_thread(_write_heartbeat, check.target))
    _disk_probes[check.target] = (future, time.monotonic())
    try:
        await asyncio.wait_for(asyncio.shield(future), timeout=check.timeout_seconds)
    except asyncio.TimeoutError:
        return False, f"disk:{check.target} write+fsync exceeded {check.timeout_seconds:g}s"
    except Exception as exc:
        del _disk_probes[check.target]
        return False, f"disk:{check.target} {_describe(exc)}"
    del _disk_probes[check.target]
    return True, None


def _describe(exc: BaseException) -> str:
    # TimeoutError has an empty str(); without the type name the event only says "failed".
    return str(exc) or type(exc).__name__


async def _run_check(check: WatchdogCheck) -> tuple[bool, str | None]:
    if check.type == "disk":
        return await _run_disk_check(check)
    if check.type == "http":
        try:
            async with httpx.AsyncClient(timeout=check.timeout_seconds) as client:
                resp = await client.get(check.target)
                return resp.status_code < 500, None
        except Exception as exc:
            return False, f"http:{check.target} {_describe(exc)}"

    host, port = _split_host_port(check.target)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=check.timeout_seconds)
    except Exception as exc:
        return False, f"{check.type}:{check.target} connect {_describe(exc)}"
    try:
        if check.type == "ssh":
            banner = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=check.timeout_seconds)
            if not banner.startswith(b"SSH-"):
                return False, f"unexpected ssh banner from {check.target}: {banner[:32]!r}"
        return True, None
    except Exception as exc:
        return False, f"{check.type}:{check.target} banner {_describe(exc)}"
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _split_host_port(target: str) -> tuple[str, int]:
    if "://" in target:
        parsed = urlparse(target)
        return parsed.hostname or "localhost", parsed.port or 80
    if ":" in target:
        host, port = target.rsplit(":", 1)
        return host, int(port)
    return target, socket.getservbyname("ssh")
