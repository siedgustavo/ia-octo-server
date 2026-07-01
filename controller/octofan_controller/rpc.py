from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlparse

from .config import RpcConfig


@dataclass
class RpcBackendStatus:
    name: str
    gpu: int
    target: str
    ok: bool
    container: str | None = None
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
    def __init__(self, docker_socket: Path = Path("/var/run/docker.sock")) -> None:
        self.docker_socket = docker_socket

    async def status(self, cfg: RpcConfig) -> RpcStatus:
        if not cfg.enabled:
            return RpcStatus(ok=True)
        backends = await asyncio.gather(
            *[
                self._check_backend(backend.name, backend.gpu, backend.target, backend.container, cfg.timeout_seconds)
                for backend in cfg.backends
            ]
        )
        errors = [f"{backend.name}: {backend.error}" for backend in backends if not backend.ok]
        return RpcStatus(ok=not errors, backends=list(backends), error="; ".join(errors) or None)

    async def _check_backend(
        self, name: str, gpu: int, target: str, container: str | None, timeout_seconds: float
    ) -> RpcBackendStatus:
        if container and self.docker_socket.exists():
            return await asyncio.to_thread(self._check_container, name, gpu, target, container, timeout_seconds)

        host, port = _split_host_port(target)
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_seconds)
            writer.close()
            await writer.wait_closed()
            return RpcBackendStatus(name=name, gpu=gpu, target=target, container=container, ok=True)
        except Exception as exc:
            return RpcBackendStatus(name=name, gpu=gpu, target=target, container=container, ok=False, error=str(exc))

    def _check_container(
        self, name: str, gpu: int, target: str, container: str, timeout_seconds: float
    ) -> RpcBackendStatus:
        try:
            payload = _docker_get_json(self.docker_socket, f"/containers/{quote(container, safe='')}/json", timeout_seconds)
            state = payload.get("State") or {}
            running = bool(state.get("Running"))
            health = (state.get("Health") or {}).get("Status")
            ok = running and health != "unhealthy"
            detail = f"state={state.get('Status') or 'unknown'}"
            if health:
                detail += f", health={health}"
            return RpcBackendStatus(
                name=name,
                gpu=gpu,
                target=target,
                container=container,
                ok=ok,
                error=None if ok else detail,
            )
        except Exception as exc:
            return RpcBackendStatus(name=name, gpu=gpu, target=target, container=container, ok=False, error=str(exc))


def _docker_get_json(socket_path: Path, path: str, timeout_seconds: float) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect(str(socket_path))
        request = f"GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"
        client.sendall(request.encode("ascii"))
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        client.close()

    response = b"".join(chunks)
    header, _, body = response.partition(b"\r\n\r\n")
    status_line = header.splitlines()[0].decode("ascii", errors="replace") if header else ""
    if " 200 " not in status_line:
        raise RuntimeError(status_line or "empty Docker response")
    return json.loads(body.decode("utf-8"))


def _split_host_port(target: str) -> tuple[str, int]:
    if "://" in target:
        parsed = urlparse(target)
        return parsed.hostname or "localhost", parsed.port or 80
    if ":" in target:
        host, port = target.rsplit(":", 1)
        return host, int(port)
    return target, socket.getservbyname("http")
