from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from .config import AiConfig


@dataclass
class AiStatus:
    ok: bool = False
    generating: bool = False
    tokens_per_second: float | None = None
    tokens_per_second_available: bool = False
    available_models: int = 0
    running_models: int = 0
    model_names: list[str] | None = None
    running_model_names: list[str] | None = None
    error: str | None = None


class AiClient:
    async def status(self, cfg: AiConfig) -> AiStatus:
        if not cfg.enabled:
            return AiStatus()
        base_urls = _base_urls(cfg)
        statuses = await asyncio.gather(
            *[self._status_for_base_url(base_url, cfg.timeout_seconds) for base_url in base_urls],
        )
        return merge_ai_statuses(statuses)

    async def _status_for_base_url(self, base_url: str, timeout_seconds: float) -> AiStatus:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                base_url = base_url.rstrip("/")
                models_resp = await client.get(f"{base_url}/v1/models")
                models_resp.raise_for_status()
        except Exception as exc:
            return AiStatus(error=str(exc))

        return parse_openai_models_status(models_resp.json())


def merge_ai_statuses(statuses: list[AiStatus]) -> AiStatus:
    if not statuses:
        return AiStatus()
    ok_statuses = [status for status in statuses if status.ok]
    if not ok_statuses:
        return AiStatus(error="; ".join(status.error or "unknown error" for status in statuses))

    model_names = sorted({name for status in ok_statuses for name in status.model_names or []})
    running_model_names = [name for status in ok_statuses for name in status.running_model_names or []]
    errors = [status.error for status in statuses if status.error]
    return AiStatus(
        ok=True,
        generating=any(status.generating for status in ok_statuses),
        tokens_per_second=None,
        tokens_per_second_available=False,
        available_models=len(model_names),
        running_models=sum(status.running_models for status in ok_statuses),
        model_names=model_names,
        running_model_names=running_model_names,
        error="; ".join(errors) if errors else None,
    )


def parse_openai_models_status(data: dict) -> AiStatus:
    models = data.get("data") or []
    model_names = [_model_name(model) for model in models]
    return AiStatus(
        ok=True,
        generating=False,
        tokens_per_second=None,
        tokens_per_second_available=False,
        available_models=len(model_names),
        running_models=len(model_names),
        model_names=model_names,
        running_model_names=model_names,
    )


def _model_name(model: dict) -> str:
    return str(model.get("id") or model.get("model") or model.get("name") or "")


def _base_urls(cfg: AiConfig) -> list[str]:
    urls = cfg.base_urls or [cfg.base_url]
    return [url.rstrip("/") for url in urls if url]
