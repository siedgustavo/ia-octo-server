from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import WatchdogCheck, WatchdogConfig


@dataclass
class WatchdogResult:
    healthy: bool
    checked: int
    errors: list[str]


async def run_watchdog_checks(cfg: WatchdogConfig) -> WatchdogResult:
    if not cfg.checks:
        return WatchdogResult(healthy=True, checked=0, errors=[])
    errors: list[str] = []
    for check in cfg.checks:
        ok, error = await _run_check(check)
        if not ok:
            errors.append(error or f"{check.type}:{check.target} failed")
    return WatchdogResult(healthy=not errors, checked=len(cfg.checks), errors=errors)


async def _run_check(check: WatchdogCheck) -> tuple[bool, str | None]:
    if check.type == "http":
        try:
            async with httpx.AsyncClient(timeout=check.timeout_seconds) as client:
                resp = await client.get(check.target)
                return resp.status_code < 500, None
        except Exception as exc:
            return False, str(exc)

    host, port = _split_host_port(check.target)
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=check.timeout_seconds)
        writer.close()
        await writer.wait_closed()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _split_host_port(target: str) -> tuple[str, int]:
    if "://" in target:
        parsed = urlparse(target)
        return parsed.hostname or "localhost", parsed.port or 80
    if ":" in target:
        host, port = target.rsplit(":", 1)
        return host, int(port)
    return target, socket.getservbyname("ssh")
