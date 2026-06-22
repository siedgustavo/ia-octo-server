from __future__ import annotations

from dataclasses import dataclass
import time

import httpx

from .config import AIRuntimeConfig


@dataclass
class AIStatus:
    ok: bool = False
    provider: str = "vllm"
    source: str = "vllm"
    generating: bool = False
    tokens_per_second: float | None = None
    tokens_per_second_available: bool = False
    available_models: int = 0
    running_models: int = 0
    model_names: list[str] | None = None
    running_model_names: list[str] | None = None
    running_requests: int = 0
    waiting_requests: int = 0
    error: str | None = None


@dataclass(frozen=True)
class VllmTokenSample:
    timestamp: float
    prompt_tokens: float = 0.0
    generation_tokens: float = 0.0

    @property
    def total_tokens(self) -> float:
        return self.prompt_tokens + self.generation_tokens


class AIRuntimeClient:
    def __init__(self) -> None:
        self._last_vllm_sample: VllmTokenSample | None = None

    async def status(self, cfg: AIRuntimeConfig) -> AIStatus:
        source = ai_source(cfg)
        if not cfg.enabled:
            return AIStatus(provider=cfg.provider, source=source)
        if cfg.provider == "ollama":
            return await self._ollama_status(cfg)
        return await self._vllm_status(cfg)

    async def _vllm_status(self, cfg: AIRuntimeConfig) -> AIStatus:
        source = ai_source(cfg)
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                base_url = cfg.base_url.rstrip("/")
                models_resp = await client.get(f"{base_url}/v1/models", headers=_headers(cfg))
                models_resp.raise_for_status()
                metrics_text = await _optional_metrics(client, base_url, cfg)
        except Exception as exc:
            return AIStatus(provider=cfg.provider, source=source, error=str(exc))

        status, sample = parse_vllm_status(
            models_resp.json(),
            metrics_text,
            previous_sample=self._last_vllm_sample,
            now=time.monotonic(),
            source=source,
        )
        self._last_vllm_sample = sample
        return status

    async def _ollama_status(self, cfg: AIRuntimeConfig) -> AIStatus:
        source = ai_source(cfg)
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                base_url = cfg.base_url.rstrip("/")
                tags_resp = await client.get(f"{base_url}/api/tags")
                tags_resp.raise_for_status()
                ps_resp = await client.get(f"{base_url}/api/ps")
                ps_resp.raise_for_status()
        except Exception as exc:
            return AIStatus(provider=cfg.provider, source=source, error=str(exc))

        return parse_ollama_status(tags_resp.json(), ps_resp.json(), source=source)


async def _optional_metrics(client: httpx.AsyncClient, base_url: str, cfg: AIRuntimeConfig) -> str | None:
    if not cfg.metrics_path:
        return None
    try:
        resp = await client.get(f"{base_url}/{cfg.metrics_path.strip('/')}", headers=_headers(cfg))
        resp.raise_for_status()
    except Exception:
        return None
    return resp.text


def _headers(cfg: AIRuntimeConfig) -> dict[str, str]:
    if not cfg.api_key:
        return {}
    return {"Authorization": f"Bearer {cfg.api_key}"}


def ai_source(cfg: AIRuntimeConfig) -> str:
    return cfg.source_label or cfg.provider


def parse_vllm_status(
    models_data: dict,
    metrics_text: str | None = None,
    previous_sample: VllmTokenSample | None = None,
    now: float | None = None,
    source: str = "vllm",
) -> tuple[AIStatus, VllmTokenSample | None]:
    models = models_data.get("data") or []
    model_names = [_openai_model_id(model) for model in models]
    samples = parse_prometheus_samples(metrics_text or "")
    running_requests = round(_sample_value(samples, "vllm:num_requests_running"))
    waiting_requests = round(_sample_value(samples, "vllm:num_requests_waiting"))
    sample = _vllm_token_sample(samples, time.monotonic() if now is None else now)
    tokens_per_second = _vllm_tokens_per_second(samples, sample, previous_sample)

    return (
        AIStatus(
            ok=True,
            provider="vllm",
            source=source,
            generating=running_requests > 0 or waiting_requests > 0,
            tokens_per_second=tokens_per_second,
            tokens_per_second_available=tokens_per_second is not None,
            available_models=len(models),
            running_models=len(models),
            model_names=model_names,
            running_model_names=model_names,
            running_requests=running_requests,
            waiting_requests=waiting_requests,
        ),
        sample,
    )


def parse_ollama_status(tags_data: dict, ps_data: dict, source: str = "ollama") -> AIStatus:
    available_models = tags_data.get("models") or []
    running_models = ps_data.get("models") or []
    model_names = [_ollama_model_name(model) for model in available_models]
    running_model_names = [_ollama_model_name(model) for model in running_models]
    return AIStatus(
        ok=True,
        provider="ollama",
        source=source,
        generating=len(running_models) > 0,
        tokens_per_second=None,
        tokens_per_second_available=False,
        available_models=len(available_models),
        running_models=len(running_models),
        model_names=model_names,
        running_model_names=running_model_names,
    )


def parse_prometheus_samples(text: str) -> dict[str, float]:
    samples: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        name = fields[0].split("{", 1)[0]
        try:
            value = float(fields[1])
        except ValueError:
            continue
        samples[name] = samples.get(name, 0.0) + value
    return samples


def _vllm_token_sample(samples: dict[str, float], now: float) -> VllmTokenSample | None:
    prompt_tokens = _sample_value(samples, "vllm:prompt_tokens_total", "vllm:prompt_tokens")
    generation_tokens = _sample_value(samples, "vllm:generation_tokens_total", "vllm:generation_tokens")
    if prompt_tokens == 0 and generation_tokens == 0:
        return None
    return VllmTokenSample(now, prompt_tokens=prompt_tokens, generation_tokens=generation_tokens)


def _vllm_tokens_per_second(
    samples: dict[str, float],
    sample: VllmTokenSample | None,
    previous_sample: VllmTokenSample | None,
) -> float | None:
    direct_tps = _sample_value(
        samples,
        "vllm:avg_prompt_throughput_toks_per_s",
        "vllm:avg_generation_throughput_toks_per_s",
    )
    if direct_tps > 0:
        return direct_tps
    if sample is None or previous_sample is None:
        return None
    elapsed = sample.timestamp - previous_sample.timestamp
    token_delta = sample.total_tokens - previous_sample.total_tokens
    if elapsed <= 0 or token_delta < 0:
        return None
    return token_delta / elapsed


def _sample_value(samples: dict[str, float], *names: str) -> float:
    return sum(samples.get(name, 0.0) for name in names)


def _openai_model_id(model: dict) -> str:
    return str(model.get("id") or "")


def _ollama_model_name(model: dict) -> str:
    return str(model.get("model") or model.get("name") or "")


OllamaStatus = AIStatus
OllamaClient = AIRuntimeClient
