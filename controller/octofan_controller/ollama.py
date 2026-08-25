from __future__ import annotations

from dataclasses import dataclass, field

import httpx


@dataclass
class OllamaLoadedModel:
    name: str = ""
    size_mib: int = 0
    expiry: str | None = None


@dataclass
class OllamaModel:
    name: str = ""
    size_bytes: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class OllamaStatus:
    base_url: str = ""
    enabled: bool = False
    up: bool = False
    running_models: int = 0
    available_models: int = 0
    vram_total_mib: int = 0
    vram_used_mib: int = 0
    loaded: list[OllamaLoadedModel] = field(default_factory=list)
    models: list[OllamaModel] = field(default_factory=list)
    error: str | None = None

    @property
    def generating(self) -> bool:
        return self.up and self.running_models > 0

    def to_dict(self) -> dict:
        return {
            "base_url": self.base_url,
            "enabled": self.enabled,
            "up": self.up,
            "running_models": self.running_models,
            "available_models": self.available_models,
            "vram_total_mib": self.vram_total_mib,
            "vram_used_mib": self.vram_used_mib,
            "loaded": [vars(model) for model in self.loaded],
            "models": [vars(model) for model in self.models],
            "error": self.error,
        }


class OllamaClient:
    async def status(
        self,
        base_url: str,
        enabled: bool,
        timeout_seconds: float,
    ) -> OllamaStatus:
        base_url = (base_url or "").rstrip("/")
        status = OllamaStatus(base_url=base_url, enabled=enabled)
        if not enabled or not base_url:
            return status

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                response = await client.get(f"{base_url}/api/ps")
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                status.error = str(exc)
                return status

            status.up = True
            status.vram_total_mib = int(data.get("size_vram_total") or 0)
            status.vram_used_mib = int(data.get("size_vram_free") or 0)
            status.vram_used_mib = status.vram_total_mib - status.vram_used_mib
            for entry in data.get("models", []) or []:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name", "")
                status.loaded.append(
                    OllamaLoadedModel(
                        name=name,
                        size_mib=int((entry.get("size") or 0) / 1024 / 1024),
                        expiry=entry.get("expires_at"),
                    )
                )
            status.running_models = len(status.loaded)
            try:
                response = await client.get(f"{base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
                models = data.get("models")
                if isinstance(models, list):
                    status.models = [
                        OllamaModel(
                            name=model.get("name", ""),
                            size_bytes=int(model.get("size") or 0),
                            details=model.get("details", {}) or {},
                        )
                        for model in models
                        if isinstance(model, dict)
                    ]
                    status.available_models = len(status.models)
            except Exception:
                pass
        return status
