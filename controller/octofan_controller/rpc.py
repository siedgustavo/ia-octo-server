from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .config import RpcConfig


@dataclass
class RpcBackendStatus:
    name: str
    gpu: int
    target: str
    ok: bool
    error: str | None = None


@dataclass
class RpcStatus:
    ok: bool = True
    backends: list[RpcBackendStatus] = field(default_factory=list)
    error: str | None = None

    @property
    def up(self) -> int:
        return sum(1 for backend in self.backends if backend.ok)

    @property
    def total(self) -> int:
        return len(self.backends)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "up": self.up,
            "total": self.total,
            "error": self.error,
            "backends": [vars(backend) for backend in self.backends],
        }


class RpcMonitor:
    async def status(self, cfg: RpcConfig) -> RpcStatus:
        if not cfg.enabled:
            return RpcStatus(ok=True)
        backends = await asyncio.gather(
            *[self._check_backend(backend.name, backend.gpu, backend.target, cfg.timeout_seconds) for backend in cfg.backends]
        )
        errors = [f"{backend.name}: {backend.error}" for backend in backends if not backend.ok]
        return RpcStatus(ok=not errors, backends=list(backends), error="; ".join(errors) or None)

    async def _check_backend(self, name: str, gpu: int, target: str, timeout_seconds: float) -> RpcBackendStatus:
        host, port = _split_host_port(target)
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_seconds)
            writer.close()
            await writer.wait_closed()
            return RpcBackendStatus(name=name, gpu=gpu, target=target, ok=True)
        except Exception as exc:
            return RpcBackendStatus(name=name, gpu=gpu, target=target, ok=False, error=str(exc))


def _split_host_port(target: str) -> tuple[str, int]:
    if "://" in target:
        parsed = urlparse(target)
        return parsed.hostname or "localhost", parsed.port or 80
    if ":" in target:
        host, port = target.rsplit(":", 1)
        return host, int(port)
    return target, socket.getservbyname("http")
