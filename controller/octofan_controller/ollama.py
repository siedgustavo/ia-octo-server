from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .config import OllamaConfig


@dataclass
class OllamaStatus:
    ok: bool = False
    generating: bool = False
    tokens_per_second: float = 0.0
    running_models: int = 0
    error: str | None = None


class OllamaClient:
    def __init__(self) -> None:
        self._last_eval_count: int | None = None
        self._last_seen: float | None = None

    async def status(self, cfg: OllamaConfig) -> OllamaStatus:
        if not cfg.enabled:
            return OllamaStatus()
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                resp = await client.get(f"{cfg.base_url.rstrip('/')}/api/ps")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return OllamaStatus(error=str(exc))

        models = data.get("models") or []
        generating = len(models) > 0
        now = time.monotonic()
        eval_count = sum(int(model.get("details", {}).get("parameter_size", "0").split(".")[0] or 0) for model in models)
        tps = 0.0
        if self._last_eval_count is not None and self._last_seen is not None and now > self._last_seen:
            # Ollama does not expose live token counters on /api/ps; this placeholder keeps
            # the interface stable until request-level instrumentation is added.
            tps = max(0.0, (eval_count - self._last_eval_count) / (now - self._last_seen))
        self._last_eval_count = eval_count
        self._last_seen = now
        return OllamaStatus(ok=True, generating=generating, tokens_per_second=tps, running_models=len(models))
