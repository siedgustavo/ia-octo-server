from __future__ import annotations

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
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                base_url = cfg.base_url.rstrip("/")
                tags_resp = await client.get(f"{base_url}/api/tags")
                tags_resp.raise_for_status()
                ps_resp = await client.get(f"{base_url}/api/ps")
                ps_resp.raise_for_status()
        except Exception as exc:
            return OllamaStatus(error=str(exc))

        return parse_ollama_status(tags_resp.json(), ps_resp.json())


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
