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


def test_migrated_models_run_on_their_dedicated_gpus():
    services = load_compose()["services"]
    llama31 = services["llamacpp-llama31-pro"]
    classifier = services["llamacpp-permission-classifier"]

    assert llama31["container_name"] == "octofan-llamacpp-llama31-pro"
    assert classifier["container_name"] == "octofan-llamacpp-permission-classifier"
    assert llama31["ports"] == ["${LLAMA31_PRO_PORT:-8082}:8080"]
    assert classifier["ports"] == ["${PERMISSION_CLASSIFIER_PORT:-8083}:8080"]
    assert llama31["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"] == ["${LLAMA31_PRO_GPU:-2}"]
    assert classifier["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"] == ["${PERMISSION_CLASSIFIER_GPU:-3}"]
    assert "comfyui" in services


def test_only_migrated_llamacpp_services_are_in_compose():
    services = load_compose()["services"]
    assert {name for name in services if name.startswith("llamacpp-")} == {
        "llamacpp-llama31-pro",
        "llamacpp-permission-classifier",
    }


def test_ollama_uses_gpu_scheduler_and_keeps_models_resident():
    ollama = load_compose()["services"]["ollama"]

    assert ollama["build"]["context"] == "./ollama"
    assert ollama["image"] == "${OLLAMA_IMAGE:-octofan/ollama:0.32.5-vram}"
    assert ollama["gpus"] == "all"
    assert ollama["environment"]["OLLAMA_KEEP_ALIVE"] == "${OLLAMA_KEEP_ALIVE:--1}"
    assert "OLLAMA_CONTEXT_LENGTH" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_KV_CACHE_TYPE"] == "${OLLAMA_KV_CACHE_TYPE:-q4_0}"
    assert "OLLAMA_MAX_LOADED_MODELS" not in ollama["environment"]
    assert ollama["environment"]["OLLAMA_NUM_PARALLEL"] == "${OLLAMA_NUM_PARALLEL:-1}"
    assert ollama["environment"]["OLLAMA_SCHED_SPREAD"] == "${OLLAMA_SCHED_SPREAD:-false}"
    assert "${MODELS_DIR:-/opt/llamacpp/models}:/models:ro" in ollama["volumes"]


def test_ollama_scheduler_patch_uses_all_available_vram_for_single_gpu_placement():
    patch = (ROOT / "ollama" / "scheduler-vram-headroom.patch").read_text(encoding="utf-8")

    assert "+\t\t\t\tif predictedForLoad > freeMemory {" in patch
    assert "+\t\t\tif predictedVRAM > candidateAvailable {" in patch
    assert "+\t\t\tif predictedVRAM > candidateAvailable*80/100 {" not in patch
    assert "f.GraphSize(uint64(numCtx), 1024, 1, envconfig.KvCacheType()" in patch
    assert "return weights + kvCache + compute + placementReserve" in patch


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

    assert "Mistral-Medium-3.5-128B-i1-GGUF:IQ2_S" in mistral
    assert "PARAMETER num_ctx 32768" in mistral
    assert "PARAMETER num_ctx 262144" in coder_next


def test_downloaded_model_tags_use_name_and_parameter_count():
    expected_sources = {
        "qwen36-fable-27b.Modelfile": "FROM qwen36-fable:27b",
        "mistral-medium-3.5-128b.Modelfile": (
            "FROM hf.co/mradermacher/Mistral-Medium-3.5-128B-i1-GGUF:IQ2_S"
        ),
        "qwen3-coder-next-80b.Modelfile": "FROM qwen3-coder-next:80b",
    }

    for filename, source in expected_sources.items():
        definition = (ROOT / "ollama" / filename).read_text(encoding="utf-8")
        assert source in definition
