from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx


@dataclass
class FluxStatus:
    base_url: str = ""
    enabled: bool = False
    up: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FluxClient:
    """Health client for the FLUX sd-server (stable-diffusion.cpp).

    sd-server has no dedicated /health endpoint; its web UI answers on `/`
    and any HTTP response below 500 counts as alive. The image generation
    itself is CPU-only, so this check never touches the GPUs.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def status(
        self,
        base_url: str,
        enabled: bool,
        timeout_seconds: float,
        health_path: str = "/",
    ) -> FluxStatus:
        base_url = (base_url or "").rstrip("/")
        status = FluxStatus(base_url=base_url, enabled=enabled)
        if not enabled or not base_url:
            return status

        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout_seconds) as client:
                response = await client.get(f"{base_url}{health_path}")
            status.up = response.status_code < 500
            if not status.up:
                status.error = f"HTTP {response.status_code}"
        except Exception as exc:
            status.error = str(exc)
        return status
