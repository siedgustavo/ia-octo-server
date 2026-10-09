from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def load_controller_config() -> dict:
    return yaml.safe_load((ROOT / "config/octofan.yaml").read_text(encoding="utf-8"))


def test_services_have_no_hard_memory_limits():
    services = load_compose()["services"]
    for service in services.values():
        assert "mem_limit" not in service
        assert "memswap_limit" not in service


def test_retired_inference_services_are_not_in_compose():
    services = load_compose()["services"]
    assert "comfyui" not in services
    assert not any(name.startswith("llamacpp-") for name in services)


def test_retired_llamacpp_health_check_is_disabled_but_host_watchdog_stays_enabled():
    config = load_controller_config()

    assert config["llamacpp"]["enabled"] is False
    assert config["llamacpp"]["servers"] == []
    assert config["watchdog"]["enabled"] is True
    assert config["watchdog"]["checks"] == [
        {
            "type": "ssh",
            "target": "host.docker.internal:22",
            "timeout_seconds": 1.0,
        }
    ]
    assert config["watchdog"]["gpus_expected"] == 4
    assert config["watchdog"]["gpu_recovery_enabled"] is True
    assert config["watchdog"]["gpu_recovery_restart_containers"] == ["octofan-ollama"]


def test_ollama_uses_gpu_scheduler_and_unloads_models_after_three_idle_hours():
    ollama = load_compose()["services"]["ollama"]

    assert ollama["build"]["dockerfile"] == "ollama-custom/Dockerfile"
    assert ollama["image"] == "${OLLAMA_IMAGE:-octofan/ollama:0.35.1-b11381}"
    assert ollama["gpus"] == "all"
    assert ollama["dns"] == ["${OLLAMA_DNS:-172.16.1.1}"]
    assert "deploy" not in ollama
    assert ollama["environment"]["OLLAMA_KEEP_ALIVE"] == "${OLLAMA_KEEP_ALIVE:-3h}"
    assert "OLLAMA_CONTEXT_LENGTH" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_KV_CACHE_TYPE"] == "${OLLAMA_KV_CACHE_TYPE:-q8_0}"
    assert "OLLAMA_MAX_LOADED_MODELS" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_NUM_PARALLEL"] == "${OLLAMA_NUM_PARALLEL:-1}"
    assert ollama["environment"]["OLLAMA_SCHED_SPREAD"] == "${OLLAMA_SCHED_SPREAD:-false}"
    assert "${MODELS_DIR:-/opt/llamacpp/models}:/models:ro" in ollama["volumes"]
    assert (
        "${MODELS_ARCHIVE_DIR:-/opt/models-archive}:/models-archive:ro"
        in ollama["volumes"]
    )


def test_downloaded_models_pin_their_workload_context():
    mistral = (ROOT / "ollama" / "mistral-medium-3.5-128b.Modelfile").read_text(
        encoding="utf-8"
    )
    coder_next = (ROOT / "ollama" / "qwen3-coder-next-80b.Modelfile").read_text(
        encoding="utf-8"
    )
    qwen38 = (ROOT / "ollama" / "qwen38-27b-q8_0.Modelfile").read_text(
        encoding="utf-8"
    )
    deepseek = (ROOT / "ollama" / "deepseek-v4-flash-284b.Modelfile").read_text(
        encoding="utf-8"
    )
    qwen_flash = (ROOT / "ollama" / "qwen3.8-flash-next.Modelfile").read_text(
        encoding="utf-8"
    )

    assert "Mistral-Medium-3.5-128B-i1-GGUF:IQ2_S" in mistral
    assert "PARAMETER num_ctx 32768" in mistral
    assert "PARAMETER num_ctx 262144" in coder_next
    assert "FROM qwen3.8:27b-q8_0" in qwen38
    assert "PARAMETER num_ctx 262144" in qwen38
    assert "FROM deepseek-v4-flash:imported" in deepseek
    assert "PARAMETER num_ctx 1048576" in deepseek
    assert "PARAMETER num_batch 128" in deepseek
    assert "PARAMETER repeat_penalty 1.0" in deepseek
    assert "PARAMETER num_ctx 262144" in qwen_flash
    assert "PARAMETER num_batch 512" in qwen_flash
    assert "PARAMETER num_ubatch 256" in qwen_flash
    assert "PARAMETER num_gpu 999" in qwen_flash
    assert "PARAMETER tensor_split 0.9,1,1,1.1" in qwen_flash


def test_downloaded_model_tags_use_name_and_parameter_count():
    expected_sources = {
        "deepseek-v4-flash-284b.Modelfile": (
            "FROM deepseek-v4-flash:imported"
        ),
        "mistral-medium-3.5-128b.Modelfile": (
            "FROM hf.co/mradermacher/Mistral-Medium-3.5-128B-i1-GGUF:IQ2_S"
        ),
        "qwen3-coder-next-80b.Modelfile": "FROM qwen3-coder-next:80b",
        "qwen38-27b-q8_0.Modelfile": "FROM qwen3.8:27b-q8_0",
        "qwen3.8-flash-next.Modelfile": "FROM /models-archive/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf",
    }

    for filename, source in expected_sources.items():
        definition = (ROOT / "ollama" / filename).read_text(encoding="utf-8")
        assert source in definition
