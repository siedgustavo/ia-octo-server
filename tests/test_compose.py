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
            "type": "tcp",
            "target": "host.docker.internal:22",
            "timeout_seconds": 1.0,
        }
    ]


def test_ollama_uses_gpu_scheduler_and_unloads_models_after_three_idle_hours():
    ollama = load_compose()["services"]["ollama"]

    assert ollama["build"]["context"] == "./ollama"
    assert ollama["image"] == "${OLLAMA_IMAGE:-octofan/ollama:0.32.13-vram}"
    assert ollama["gpus"] == "all"
    assert ollama["dns"] == ["${OLLAMA_DNS:-172.16.1.1}"]
    assert "deploy" not in ollama
    assert ollama["environment"]["OLLAMA_KEEP_ALIVE"] == "${OLLAMA_KEEP_ALIVE:-3h}"
    assert "OLLAMA_CONTEXT_LENGTH" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_KV_CACHE_TYPE"] == "${OLLAMA_KV_CACHE_TYPE:-q4_0}"
    assert "OLLAMA_MAX_LOADED_MODELS" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_NUM_PARALLEL"] == "${OLLAMA_NUM_PARALLEL:-1}"
    assert ollama["environment"]["OLLAMA_SCHED_SPREAD"] == "${OLLAMA_SCHED_SPREAD:-false}"
    assert "${MODELS_DIR:-/opt/llamacpp/models}:/models:ro" in ollama["volumes"]
    assert (
        "${MODELS_ARCHIVE_DIR:-/opt/models-archive}:/models-archive:ro"
        in ollama["volumes"]
    )


def test_ollama_scheduler_patch_uses_all_available_vram_for_single_gpu_placement():
    patch = (ROOT / "ollama" / "scheduler-vram-headroom.patch").read_text(encoding="utf-8")

    assert "+\t\t\t\tif predictedForLoad > freeMemory {" in patch
    assert "+\t\t\tif predictedVRAM > candidateAvailable {" in patch
    assert "+\t\t\tif predictedVRAM > candidateAvailable*80/100 {" not in patch
    assert "f.GraphSize(uint64(numCtx), 1024, 1, envconfig.KvCacheType()" in patch
    assert "return weights + kvCache + compute + placementReserve" in patch


def test_deepseek_v4_ktransformers_is_an_opt_in_dedicated_service():
    service = load_compose()["services"]["deepseek-v4-ktransformers"]

    assert service["image"] == "${KTRANSFORMERS_IMAGE:-approachingai/ktransformers:DSV4-specific}"
    assert service["profiles"] == ["ktransformers"]
    assert service["gpus"] == "all"
    assert service["ipc"] == "host"
    assert service["cap_add"] == ["SYS_NICE"]
    assert service["command"] == [
        "--served-model-name",
        "deepseek-v4-flash-284b-ktransformers",
        "--reasoning-parser",
        "deepseek-v4",
        "--tool-call-parser",
        "deepseekv4",
        "--enable-metrics",
    ]
    assert service["environment"]["TP"] == "${KTRANSFORMERS_TP:-4}"
    assert service["environment"]["MEM_FRACTION"] == "${KTRANSFORMERS_MEM_FRACTION:-0.98}"
    assert service["environment"]["KT_GPU_EXPERTS"] == "${KTRANSFORMERS_GPU_EXPERTS:-96}"
    assert service["environment"]["KT_CPUINFER_THREADS"] == "${KTRANSFORMERS_CPUINFER_THREADS:-28}"
    assert service["environment"]["KT_THREADPOOL_COUNT"] == "${KTRANSFORMERS_THREADPOOL_COUNT:-2}"
    assert service["environment"]["CONTEXT_LENGTH"] == "${KTRANSFORMERS_CONTEXT_LENGTH:-1048576}"
    assert service["environment"]["MAX_RUNNING_REQUESTS"] == "${KTRANSFORMERS_MAX_RUNNING_REQUESTS:-1}"
    assert "${KTRANSFORMERS_MODEL_DIR:-/opt/models-archive/DeepSeek-V4-Flash-0731}:/model:ro" in service["volumes"]


def test_ollama_local_models_use_tuned_inference_parameters():
    for filename in (
        "qwen3coder.Modelfile",
        "qwen36-uncensored.Modelfile",
        "qwen3coder-alias-256k.Modelfile",
        "qwen36-alias-256k.Modelfile",
    ):
        definition = (ROOT / "ollama" / filename).read_text(encoding="utf-8")
        assert "PARAMETER num_ctx 262144" in definition
        assert "PARAMETER num_batch 128" in definition
        assert "PARAMETER num_gpu" not in definition
        assert "PARAMETER repeat_penalty 1.0" in definition


def test_archived_local_models_use_the_read_only_archive_mount():
    qwen36 = (ROOT / "ollama" / "qwen36-uncensored.Modelfile").read_text(
        encoding="utf-8"
    )
    qwen3coder = (ROOT / "ollama" / "qwen3coder.Modelfile").read_text(
        encoding="utf-8"
    )

    assert "FROM /models-archive/qwen3.6/" in qwen36
    assert "Aggressive-Q8_K_P.gguf" in qwen36
    assert "mmproj-Qwen3.6-35B" in qwen36
    assert "FROM /models-archive/qwen3coder/30b-iq4_xs/" in qwen3coder


def test_qwen36_fable_uses_its_native_maximum_context():
    definition = (ROOT / "ollama" / "qwen36-fable-27b.Modelfile").read_text(encoding="utf-8")

    assert "FROM qwen36-fable:27b" in definition
    assert "PARAMETER num_ctx 262144" in definition


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

    assert "Mistral-Medium-3.5-128B-i1-GGUF:IQ2_S" in mistral
    assert "PARAMETER num_ctx 32768" in mistral
    assert "PARAMETER num_ctx 262144" in coder_next
    assert "FROM qwen3.8:27b-q8_0" in qwen38
    assert "PARAMETER num_ctx 262144" in qwen38
    assert "FROM deepseek-v4-flash:imported" in deepseek
    assert "PARAMETER num_ctx 1048576" in deepseek
    assert "PARAMETER num_batch 128" in deepseek
    assert "PARAMETER repeat_penalty 1.0" in deepseek


def test_downloaded_model_tags_use_name_and_parameter_count():
    expected_sources = {
        "deepseek-v4-flash-284b.Modelfile": (
            "FROM deepseek-v4-flash:imported"
        ),
        "qwen36-fable-27b.Modelfile": "FROM qwen36-fable:27b",
        "mistral-medium-3.5-128b.Modelfile": (
            "FROM hf.co/mradermacher/Mistral-Medium-3.5-128B-i1-GGUF:IQ2_S"
        ),
        "qwen3-coder-next-80b.Modelfile": "FROM qwen3-coder-next:80b",
        "qwen38-27b-q8_0.Modelfile": "FROM qwen3.8:27b-q8_0",
    }

    for filename, source in expected_sources.items():
        definition = (ROOT / "ollama" / filename).read_text(encoding="utf-8")
        assert source in definition
