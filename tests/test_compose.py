import json

import pytest
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
        },
        {
            "type": "disk",
            "target": "/watchdog/heartbeat",
            "timeout_seconds": 10.0,
        },
    ]
    assert config["watchdog"]["gpus_expected"] == 4
    assert config["watchdog"]["gpu_recovery_enabled"] is True
    assert config["watchdog"]["gpu_recovery_restart_containers"] == ["strata-qwen", "maya-deepseek"]
    assert config["watchdog"]["ai_recovery_enabled"] is True
    assert config["watchdog"]["ai_recovery_min_failures"] == 3
    assert config["watchdog"]["ai_recovery_cooldown_seconds"] == 900
    assert config["watchdog"]["ai_recovery_restart_containers"] == ["strata-qwen", "maya-deepseek"]
    assert config["ollama"]["enabled"] is False
    assert config["strata"]["enabled"] is True
    assert config["strata"]["base_url"] == "http://host.docker.internal:18080"
    assert [(e["name"], e["base_url"]) for e in config["strata"]["endpoints"]] == [
        ("Strata", "http://host.docker.internal:18080"),
        ("Maya", "http://host.docker.internal:18090"),
    ]
    assert config["flux"]["enabled"] is True
    assert config["flux"]["base_url"] == "http://host.docker.internal:7860"


def test_ollama_was_removed_from_the_main_compose():
    # Retirado del server el 2026-11-19 (modelos archivados en inference2: docs/ollama-store-archive.md).
    assert "ollama" not in load_compose()["services"]

def test_ollama_image_pins_context_shift_to_avoid_reload_thrash():
    dockerfile = (ROOT / "ollama-custom" / "Dockerfile").read_text(encoding="utf-8")
    patch = (ROOT / "ollama-custom" / "ollama-context-shift-pin.patch").read_text(
        encoding="utf-8"
    )

    assert "COPY ollama-custom/ollama-context-shift-pin.patch" in dockerfile
    assert "git apply /tmp/ollama-context-shift-pin.patch" in dockerfile
    assert 'envconfig.Var("OLLAMA_CONTEXT_SHIFT")' in patch
    assert "TestSchedNeedsReloadIgnoresClientShiftWhenServerPinsContextShift" in patch


def test_ollama_image_passes_prompt_cache_ram_to_llama_server():
    dockerfile = (ROOT / "ollama-custom" / "Dockerfile").read_text(encoding="utf-8")
    patch = (ROOT / "ollama-custom" / "ollama-cache-ram.patch").read_text(
        encoding="utf-8"
    )

    assert "COPY ollama-custom/ollama-cache-ram.patch" in dockerfile
    assert "git apply /tmp/ollama-cache-ram.patch" in dockerfile
    assert 'envconfig.Var("OLLAMA_CACHE_RAM_MIB")' in patch
    assert '"--cache-ram"' in patch


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


def test_qwen_flash_uncensored_mirrors_qwen_flash_tuning():
    definitions = ROOT / "ollama"
    qwen_flash = (definitions / "qwen3.8-flash-next.Modelfile").read_text(
        encoding="utf-8"
    )
    uncensored = (
        definitions / "qwen3.8-flash-next-uncensored.Modelfile"
    ).read_text(encoding="utf-8")

    def parameters(definition):
        return [line for line in definition.splitlines() if line.startswith("PARAMETER ")]

    assert parameters(uncensored) == parameters(qwen_flash)
    assert (
        "FROM /models-archive/Qwen3.8-Flash-Next-Uncensored-Q4_K_S/"
        "mmproj-Qwen3.8-Flash-Next-Uncensored-F16.gguf"
    ) in uncensored


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
        "qwen3.8-flash-next-uncensored.Modelfile": "FROM /models-archive/Qwen3.8-Flash-Next-Uncensored-Q4_K_S/Qwen3.8-Flash-Next-Uncensored-Q4_K_S-00001-of-00003.gguf",
    }

    for filename, source in expected_sources.items():
        definition = (ROOT / "ollama" / filename).read_text(encoding="utf-8")
        assert source in definition


def test_flux_cpu_stack_is_isolated_and_gpu_free():
    compose = yaml.safe_load((ROOT / "docker-compose.flux.yml").read_text(encoding="utf-8"))
    # Proyecto propio: el stack principal no debe verlo como huerfano.
    assert compose["name"] != "ia-octo-server"
    flux = compose["services"]["flux"]

    assert "gpus" not in flux
    assert "mem_limit" not in flux
    assert flux["entrypoint"] == ["/sd-server"]
    command = flux["command"]
    assert command[command.index("--steps") + 1] == "4"
    assert command[command.index("--cfg-scale") + 1] == "1.0"
    assert command[command.index("--diffusion-model") + 1] == "/models/flux1-schnell-q8_0.gguf"


def test_maya_deepseek_stack_is_isolated_from_strata():
    compose = yaml.safe_load((ROOT / "docker-compose.maya-deepseek.yml").read_text(encoding="utf-8"))
    strata = yaml.safe_load((ROOT / "docker-compose.strata-qwen.yml").read_text(encoding="utf-8"))
    # Proyecto propio: --remove-orphans del principal no lo borra.
    assert compose["name"] not in ("ia-octo-server", None)
    maya = compose["services"]["maya-deepseek"]

    assert maya["container_name"] != strata["services"]["strata-qwen"]["container_name"]
    # llama-swap decide cual corre: Docker no levanta ninguno solo (ni tras un reboot).
    assert maya["restart"] == "no"
    assert strata["services"]["strata-qwen"]["restart"] == "no"
    assert "mem_limit" not in maya
    assert maya["ulimits"]["memlock"] == {"soft": -1, "hard": -1}
    assert maya["ports"][0].endswith(":${MAYA_PORT:-18090}:8080")


MAYA_CONFIGS = ("maya/maya-deepseek.json", "maya/maya-deepseek-128g.json")


@pytest.mark.parametrize("path", MAYA_CONFIGS)
def test_maya_deepseek_pins_native_context(path):
    config = json.loads((ROOT / path).read_text(encoding="utf-8"))
    args = config["args"]
    # Maximo nativo de DeepSeek-V4.1-Flash (max_position_embeddings): 1M.
    assert int(args[args.index("--max-context") + 1]) == 1048576
    assert args[args.index("--pack") + 1].startswith("/models/")
    assert config["model_name"] == "deepseek-v4.1-flash-abliterated"


@pytest.mark.parametrize("path", MAYA_CONFIGS)
def test_maya_deepseek_keeps_vision_enabled(path):
    config = json.loads((ROOT / path).read_text(encoding="utf-8"))
    # La torre de vision va en el pack (tools/ds4/vision_pack.py): no apagarla en la config.
    assert "--vision" not in config["args"]
