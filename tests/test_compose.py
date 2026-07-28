from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_services_have_no_hard_memory_limits():
    services = load_compose()["services"]
    for service in services.values():
        assert "mem_limit" not in service
        assert "memswap_limit" not in service


def test_migrated_models_are_not_in_compose():
    services = load_compose()["services"]
    assert "llamacpp-llama31-pro" not in services
    assert "llamacpp-permission-classifier" not in services
    assert "comfyui" in services


def test_llamacpp_services_are_not_in_compose():
    services = load_compose()["services"]
    assert not any(name.startswith("llamacpp-") for name in services)


def test_ollama_uses_both_gpus_and_keeps_models_resident():
    ollama = load_compose()["services"]["ollama"]

    assert ollama["gpus"] == "all"
    assert ollama["environment"]["OLLAMA_KEEP_ALIVE"] == "${OLLAMA_KEEP_ALIVE:--1}"
    assert "OLLAMA_MAX_LOADED_MODELS" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_NUM_PARALLEL"] == "${OLLAMA_NUM_PARALLEL:-1}"
    assert "${MODELS_DIR:-/opt/llamacpp/models}:/models:ro" in ollama["volumes"]


def test_ollama_local_models_use_tuned_inference_parameters():
    for filename in ("qwen3coder.Modelfile", "qwen36-uncensored.Modelfile"):
        definition = (ROOT / "ollama" / filename).read_text(encoding="utf-8")
        assert "PARAMETER num_batch 128" in definition
        assert "PARAMETER repeat_penalty 1.0" in definition
