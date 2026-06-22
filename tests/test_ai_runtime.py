from octofan_controller.ai_runtime import VllmTokenSample, parse_ollama_status, parse_prometheus_samples, parse_vllm_status
from octofan_controller.config import AppConfig, migrate_config_data


def test_parse_ollama_status_counts_available_and_running_models():
    status = parse_ollama_status(
        {
            "models": [
                {"name": "deepseek-coder:33b"},
                {"model": "qwen3-coder:30b"},
            ]
        },
        {"models": [{"name": "qwen3-coder:30b"}]},
    )

    assert status.ok
    assert status.available_models == 2
    assert status.running_models == 1
    assert status.model_names == ["deepseek-coder:33b", "qwen3-coder:30b"]
    assert status.running_model_names == ["qwen3-coder:30b"]


def test_parse_ollama_status_does_not_invent_tokens_per_second():
    status = parse_ollama_status({"models": []}, {"models": []})

    assert status.tokens_per_second is None
    assert not status.tokens_per_second_available


def test_parse_vllm_status_counts_served_models_and_activity():
    metrics = """
# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{model_name="qwen3-coder:30b"} 2.0
vllm:num_requests_waiting{model_name="qwen3-coder:30b"} 1.0
vllm:prompt_tokens_total{model_name="qwen3-coder:30b"} 150.0
vllm:generation_tokens_total{model_name="qwen3-coder:30b"} 90.0
"""

    status, sample = parse_vllm_status(
        {"data": [{"id": "qwen3-coder:30b"}]},
        metrics,
        previous_sample=VllmTokenSample(timestamp=10.0, prompt_tokens=100.0, generation_tokens=50.0),
        now=20.0,
    )

    assert status.ok
    assert status.provider == "vllm"
    assert status.generating
    assert status.available_models == 1
    assert status.running_models == 1
    assert status.model_names == ["qwen3-coder:30b"]
    assert status.running_requests == 2
    assert status.waiting_requests == 1
    assert status.tokens_per_second == 9.0
    assert status.tokens_per_second_available
    assert sample == VllmTokenSample(timestamp=20.0, prompt_tokens=150.0, generation_tokens=90.0)


def test_parse_prometheus_samples_sums_labels():
    samples = parse_prometheus_samples(
        """
vllm:num_requests_running{model_name="a"} 1.0
vllm:num_requests_running{model_name="b"} 2.0
"""
    )

    assert samples["vllm:num_requests_running"] == 3.0


def test_legacy_ollama_config_migrates_to_ai_runtime():
    data = migrate_config_data({"ollama": {"enabled": True, "base_url": "http://ollama:11434"}})
    cfg = AppConfig.model_validate(data)

    assert cfg.ai.enabled
    assert cfg.ai.provider == "ollama"
    assert cfg.ai.base_url == "http://ollama:11434"
