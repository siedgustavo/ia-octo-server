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
