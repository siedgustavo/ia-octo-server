from __future__ import annotations

import os

import httpx


DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")


class DockerApiClient:
    def __init__(self, socket_path: str = DOCKER_SOCKET, transport: httpx.BaseTransport | None = None) -> None:
        self.socket_path = socket_path
        self._transport = transport

    def restart_container(self, name: str, timeout_seconds: float = 90.0) -> bool:
        try:
            transport = self._transport or httpx.HTTPTransport(uds=self.socket_path)
            with httpx.Client(transport=transport, timeout=timeout_seconds) as client:
                resp = client.post(f"http://docker/containers/{name}/restart", params={"t": 10})
            return resp.status_code in (204, 304)
        except Exception:
            return False

    def container_health(self, name: str, timeout_seconds: float = 5.0) -> str | None:
        """Return State.Health.Status ("starting", "healthy", "unhealthy") or None."""
        try:
            transport = self._transport or httpx.HTTPTransport(uds=self.socket_path)
            with httpx.Client(transport=transport, timeout=timeout_seconds) as client:
                resp = client.get(f"http://docker/containers/{name}/json")
                if resp.status_code != 200:
                    return None
                state = resp.json().get("State") or {}
                health = state.get("Health") or {}
            value = health.get("status")
            return value if isinstance(value, str) else None
        except Exception:
            return None
