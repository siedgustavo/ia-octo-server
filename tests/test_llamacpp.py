from octofan_controller.config import LlamaCppServerConfig
from octofan_controller.llamacpp import (
    LlamaCppServerStatus,
    merge_llamacpp_statuses,
    parse_llamacpp_server_status,
)


def server_config(name: str = "qwen3coder:30b", gpu: str = "0", model: str = "qwen3coder:30b") -> LlamaCppServerConfig:
    return LlamaCppServerConfig(
        name=name,
        gpu=gpu,
        base_url=f"http://llamacpp-{name}:8080",
        expected_model=model,
    )


def test_parse_llamacpp_status_counts_healthy_server():
    status = parse_llamacpp_server_status(
        server_config(),
        {
            "model_path": "/models/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated.i1-IQ4_XS.gguf",
            "default_generation_settings": {"n_ctx": 65536},
            "total_slots": 2,
        },
        [{"id": 0, "is_processing": False}, {"id": 1, "is_processing": False}],
        {"data": [{"id": "qwen3coder:30b"}]},
    )

    assert status.ok
    assert status.model == "qwen3coder:30b"
    assert status.context_size == 65536
    assert status.total_slots == 2
    assert status.processing_slots == 0
    assert not status.generating


def test_merge_llamacpp_statuses_reports_all_servers_healthy():
    status = merge_llamacpp_statuses(
        [
            LlamaCppServerStatus(name="qwen3coder:30b", gpu="0", ok=True, model="qwen3coder:30b", total_slots=1),
            LlamaCppServerStatus(name="qwen3.6:35b", gpu="1", ok=True, model="qwen3.6:35b", total_slots=1),
            LlamaCppServerStatus(name="llama3.1:8b", gpu="2", ok=True, model="llama3.1:8b", total_slots=1),
        ]
    )

    assert status.ok
    assert status.available_models == 3
    assert status.running_models == 0
    assert status.model_names == ["llama3.1:8b", "qwen3.6:35b", "qwen3coder:30b"]
    assert status.error is None


def test_merge_llamacpp_statuses_reports_partial_failure():
    status = merge_llamacpp_statuses(
        [
            LlamaCppServerStatus(name="qwen3coder:30b", gpu="0", ok=True, model="qwen3coder:30b", total_slots=1),
            LlamaCppServerStatus(name="qwen3.6:35b", gpu="1", ok=False, expected_model="qwen3.6:35b", error="connect failed"),
        ]
    )

    assert not status.ok
    assert status.available_models == 1
    assert status.model_names == ["qwen3coder:30b"]
    assert "qwen3.6:35b: connect failed" in (status.error or "")


def test_parse_llamacpp_slots_detects_generation():
    status = parse_llamacpp_server_status(
        server_config(model="llama3.1:8b"),
        {"model": "llama31-pro.gguf", "n_ctx": 8192},
        [{"id": 0, "is_processing": True}, {"id": 1, "is_processing": False}],
        {"data": [{"id": "llama3.1:8b"}]},
    )

    assert status.generating
    assert status.processing_slots == 1


def test_parse_llamacpp_rejects_missing_model():
    try:
        parse_llamacpp_server_status(server_config(), {"total_slots": 1}, [])
    except ValueError as exc:
        assert "model" in str(exc)
    else:
        raise AssertionError("expected invalid /props response")


def test_parse_llamacpp_rejects_invalid_slots():
    try:
        parse_llamacpp_server_status(server_config(), {"model": "Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated.i1-IQ4_XS.gguf"}, {"id": 0})
    except ValueError as exc:
        assert "/slots" in str(exc)
    else:
        raise AssertionError("expected invalid /slots response")
