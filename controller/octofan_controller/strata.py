from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import httpx


@dataclass
class StrataModel:
    id: str = ""
    loaded: bool = False
    context_size: int | None = None


@dataclass
class StrataStatus:
    name: str = "Strata"
    base_url: str = ""
    enabled: bool = False
    up: bool = False
    total_models: int = 0
    loaded_models: int = 0
    models: list[StrataModel] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrataClient:
    """Health client for the Strata OpenAI-compatible API (`/v1/models`)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def status(
        self,
        base_url: str,
        enabled: bool,
        timeout_seconds: float,
    ) -> StrataStatus:
        base_url = (base_url or "").rstrip("/")
        status = StrataStatus(base_url=base_url, enabled=enabled)
        if not enabled or not base_url:
            return status

        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout_seconds) as client:
                response = await client.get(f"{base_url}/v1/models")
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            status.error = str(exc)
            return status

        status.up = True
        status.models = parse_strata_models(data)
        status.total_models = len(status.models)
        status.loaded_models = sum(1 for model in status.models if model.loaded)
        return status


    async def status_any(
        self,
        endpoints: list[tuple[str, str]],
        enabled: bool,
        timeout_seconds: float,
    ) -> StrataStatus:
        """First endpoint that answers, as (name, base_url) pairs in order.

        Strata and Maya share the GPUs and take turns, so one of them being up is
        healthy. With none up, the status keeps the first endpoint's base_url (so
        the watchdog still judges it) and every endpoint's error.
        """
        if not endpoints:
            return StrataStatus(enabled=enabled)
        errors: list[str] = []
        first: StrataStatus | None = None
        for name, base_url in endpoints:
            status = await self.status(base_url, enabled, timeout_seconds)
            status.name = name
            if status.up or not enabled:
                return status
            first = first or status
            errors.append(f"{name}: {status.error}")
        assert first is not None
        first.error = "; ".join(errors)
        return first


def parse_strata_models(data: Any) -> list[StrataModel]:
    if not isinstance(data, dict):
        return []
    entries = data.get("data")
    if not isinstance(entries, list):
        return []
    models: list[StrataModel] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        state = entry.get("status")
        loaded = isinstance(state, dict) and state.get("value") == "loaded"
        meta = entry.get("meta")
        context_size = meta.get("n_ctx") if isinstance(meta, dict) else None
        models.append(
            StrataModel(
                id=str(entry.get("id") or ""),
                loaded=loaded,
                context_size=context_size if isinstance(context_size, int) else None,
            )
        )
    return models
