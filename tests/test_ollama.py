from octofan_controller.ollama import parse_ollama_status


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
