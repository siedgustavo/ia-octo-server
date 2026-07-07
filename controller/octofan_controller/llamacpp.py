from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any

import httpx

from .config import LlamaCppConfig, LlamaCppServerConfig


@dataclass
class LlamaCppServerStatus:
    name: str
    gpu: str
    ok: bool = False
    generating: bool = False
    model: str | None = None
    expected_model: str | None = None
    context_size: int | None = None
    total_slots: int = 0
    processing_slots: int = 0
    error: str | None = None


@dataclass
class LlamaCppStatus:
    ok: bool = False
    generating: bool = False
    tokens_per_second: float | None = None
    tokens_per_second_available: bool = False
    available_models: int = 0
    running_models: int = 0
    model_names: list[str] = field(default_factory=list)
    running_model_names: list[str] = field(default_factory=list)
    servers: list[LlamaCppServerStatus] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LlamaCppClient:
    async def status(self, cfg: LlamaCppConfig) -> LlamaCppStatus:
        if not cfg.enabled:
            return LlamaCppStatus()
        statuses = await asyncio.gather(
            *[self._status_for_server(server, cfg.timeout_seconds) for server in cfg.servers],
        )
        return merge_llamacpp_statuses(statuses)

    async def _status_for_server(self, server: LlamaCppServerConfig, timeout_seconds: float) -> LlamaCppServerStatus:
        base_url = server.base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                health_resp = await client.get(f"{base_url}/health")
                health_resp.raise_for_status()
                props_resp = await client.get(f"{base_url}/props")
                props_resp.raise_for_status()
                slots_resp = await client.get(f"{base_url}/slots")
                slots_resp.raise_for_status()
                models_resp = await client.get(f"{base_url}/v1/models")
                models_resp.raise_for_status()
        except Exception as exc:
            return LlamaCppServerStatus(
                name=server.name,
                gpu=server.gpu,
                expected_model=server.expected_model,
                error=str(exc),
            )

        try:
            return parse_llamacpp_server_status(
                server,
                props_resp.json(),
                slots_resp.json(),
                models_resp.json(),
            )
        except Exception as exc:
            return LlamaCppServerStatus(
                name=server.name,
                gpu=server.gpu,
                expected_model=server.expected_model,
                error=f"invalid response: {exc}",
            )


def merge_llamacpp_statuses(statuses: list[LlamaCppServerStatus]) -> LlamaCppStatus:
    if not statuses:
        return LlamaCppStatus()

    ok_statuses = [status for status in statuses if status.ok]
    model_names = sorted({status.model for status in ok_statuses if status.model})
    running_model_names = [
        status.model
        for status in ok_statuses
        if status.generating and status.model is not None
    ]
    errors = [f"{status.name}: {status.error or 'unknown error'}" for status in statuses if not status.ok]
    return LlamaCppStatus(
        ok=len(ok_statuses) == len(statuses),
        generating=any(status.generating for status in ok_statuses),
        tokens_per_second=None,
        tokens_per_second_available=False,
        available_models=len(model_names),
        running_models=len(running_model_names),
        model_names=model_names,
        running_model_names=running_model_names,
        servers=statuses,
        error="; ".join(errors) if errors else None,
    )


def parse_llamacpp_server_status(
    server: LlamaCppServerConfig,
    props_data: dict[str, Any],
    slots_data: Any,
    models_data: Any | None = None,
) -> LlamaCppServerStatus:
    if not isinstance(props_data, dict):
        raise ValueError("/props is not an object")
    if not isinstance(slots_data, list):
        raise ValueError("/slots is not a list")

    model = _served_model_name(models_data) or _model_name(props_data)
    if not model:
        raise ValueError("/props did not include a model")

    total_slots = _total_slots(props_data, slots_data)
    processing_slots = sum(1 for slot in slots_data if isinstance(slot, dict) and _slot_is_processing(slot))
    return LlamaCppServerStatus(
        name=server.name,
        gpu=server.gpu,
        ok=_model_matches(model, server.expected_model),
        generating=processing_slots > 0,
        model=model,
        expected_model=server.expected_model,
        context_size=_context_size(props_data),
        total_slots=total_slots,
        processing_slots=processing_slots,
        error=None if _model_matches(model, server.expected_model) else f"expected model {server.expected_model}, got {model}",
    )


def _model_name(props_data: dict[str, Any]) -> str | None:
    for key in ("model", "model_name", "model_path"):
        value = props_data.get(key)
        if isinstance(value, str) and value:
            return PurePosixPath(value).name
    return None


def _served_model_name(models_data: Any) -> str | None:
    if not isinstance(models_data, dict):
        return None
    models = models_data.get("data")
    if not isinstance(models, list) or not models:
        return None
    first = models[0]
    if not isinstance(first, dict):
        return None
    value = first.get("id")
    return value if isinstance(value, str) and value else None


def _context_size(props_data: dict[str, Any]) -> int | None:
    for key in ("n_ctx", "context_size"):
        value = props_data.get(key)
        if isinstance(value, int):
            return value
    settings = props_data.get("default_generation_settings")
    if isinstance(settings, dict) and isinstance(settings.get("n_ctx"), int):
        return settings["n_ctx"]
    return None


def _total_slots(props_data: dict[str, Any], slots_data: list[Any]) -> int:
    value = props_data.get("total_slots")
    if isinstance(value, int):
        return value
    return len(slots_data)


def _slot_is_processing(slot: dict[str, Any]) -> bool:
    return bool(slot.get("is_processing") or slot.get("processing") or slot.get("state") == "processing")


def _model_matches(model: str, expected_model: str) -> bool:
    return model == expected_model or PurePosixPath(model).name == PurePosixPath(expected_model).name
