from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from .config import OllamaConfig


@dataclass
class OllamaStatus:
    ok: bool = False
    generating: bool = False
    tokens_per_second: float | None = None
    tokens_per_second_available: bool = False
    available_models: int = 0
    running_models: int = 0
    model_names: list[str] | None = None
    running_model_names: list[str] | None = None
    error: str | None = None


class OllamaClient:
    async def status(self, cfg: OllamaConfig) -> OllamaStatus:
        if not cfg.enabled:
            return OllamaStatus()
        base_urls = _base_urls(cfg)
        statuses = await asyncio.gather(
            *[self._status_for_base_url(base_url, cfg.timeout_seconds) for base_url in base_urls],
        )
        return merge_ollama_statuses(statuses)

    async def _status_for_base_url(self, base_url: str, timeout_seconds: float) -> OllamaStatus:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                base_url = base_url.rstrip("/")
                tags_resp = await client.get(f"{base_url}/api/tags")
                tags_resp.raise_for_status()
                ps_resp = await client.get(f"{base_url}/api/ps")
                ps_resp.raise_for_status()
        except Exception as exc:
            return OllamaStatus(error=str(exc))

        return parse_ollama_status(tags_resp.json(), ps_resp.json())


def merge_ollama_statuses(statuses: list[OllamaStatus]) -> OllamaStatus:
    if not statuses:
        return OllamaStatus()
    ok_statuses = [status for status in statuses if status.ok]
    if not ok_statuses:
        return OllamaStatus(error="; ".join(status.error or "unknown error" for status in statuses))

    model_names = sorted({name for status in ok_statuses for name in status.model_names or []})
    running_model_names = [name for status in ok_statuses for name in status.running_model_names or []]
    errors = [status.error for status in statuses if status.error]
    return OllamaStatus(
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


def parse_ollama_status(tags_data: dict, ps_data: dict) -> OllamaStatus:
    available_models = tags_data.get("models") or []
    running_models = ps_data.get("models") or []
    model_names = [_model_name(model) for model in available_models]
    running_model_names = [_model_name(model) for model in running_models]
    return OllamaStatus(
        ok=True,
        generating=len(running_models) > 0,
        tokens_per_second=None,
        tokens_per_second_available=False,
        available_models=len(available_models),
        running_models=len(running_models),
        model_names=model_names,
        running_model_names=running_model_names,
    )


def _model_name(model: dict) -> str:
    return str(model.get("model") or model.get("name") or "")


def _base_urls(cfg: OllamaConfig) -> list[str]:
    urls = cfg.base_urls or [cfg.base_url]
    return [url.rstrip("/") for url in urls if url]
