from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_every_service_has_a_hard_memory_budget():
    services = load_compose()["services"]
    expected = {
        "octofan-controller": ("${OCTOFAN_CONTROLLER_MEM_LIMIT:-192m}", "${OCTOFAN_CONTROLLER_MEMSWAP_LIMIT:-384m}"),
        "prometheus": ("${PROMETHEUS_MEM_LIMIT:-256m}", "${PROMETHEUS_MEMSWAP_LIMIT:-768m}"),
        "node-exporter": ("${NODE_EXPORTER_MEM_LIMIT:-64m}", "${NODE_EXPORTER_MEMSWAP_LIMIT:-128m}"),
        "grafana": ("${GRAFANA_MEM_LIMIT:-256m}", "${GRAFANA_MEMSWAP_LIMIT:-512m}"),
        "llamacpp-qwen3coder": ("${QWEN3CODER_MEM_LIMIT:-2g}", "${QWEN3CODER_MEMSWAP_LIMIT:-9g}"),
        "llamacpp-qwen36-uncensored": (
            "${QWEN36_UNCENSORED_MEM_LIMIT:-4g}",
            "${QWEN36_UNCENSORED_MEMSWAP_LIMIT:-10g}",
        ),
        "llamacpp-llama31-pro": ("${LLAMA31_PRO_MEM_LIMIT:-1536m}", "${LLAMA31_PRO_MEMSWAP_LIMIT:-7g}"),
        "llamacpp-permission-classifier": (
            "${PERMISSION_CLASSIFIER_MEM_LIMIT:-1g}",
            "${PERMISSION_CLASSIFIER_MEMSWAP_LIMIT:-5g}",
        ),
        "comfyui": ("${COMFYUI_MEM_LIMIT:-2g}", "${COMFYUI_MEMSWAP_LIMIT:-4g}"),
    }

    assert services.keys() == expected.keys()
    for service_name, (memory, memory_swap) in expected.items():
        assert services[service_name]["mem_limit"] == memory
        assert services[service_name]["memswap_limit"] == memory_swap


def test_classifier_does_not_replace_comfyui_and_caps_prompt_cache():
    services = load_compose()["services"]
    classifier = services["llamacpp-permission-classifier"]

    assert "comfyui" in services
    cache_flag_index = classifier["command"].index("--cache-ram")
    assert classifier["command"][cache_flag_index + 1] == "${PERMISSION_CLASSIFIER_CACHE_RAM_MIB:-256}"
