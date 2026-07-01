from octofan_controller.ai import AiStatus, merge_ai_statuses, parse_openai_models_status


def test_parse_openai_models_status_counts_available_and_loaded_models():
    status = parse_openai_models_status(
        {
            "object": "list",
            "data": [
                {"id": "qwen3coder-35b"},
                {"id": "llama3.1-pro"},
            ],
        }
    )

    assert status.ok
    assert status.available_models == 2
    assert status.running_models == 2
    assert status.model_names == ["qwen3coder-35b", "llama3.1-pro"]
    assert status.running_model_names == ["qwen3coder-35b", "llama3.1-pro"]


def test_parse_openai_models_status_does_not_invent_tokens_per_second():
    status = parse_openai_models_status({"data": []})

    assert status.tokens_per_second is None
    assert not status.tokens_per_second_available


def test_merge_ai_statuses_aggregates_multi_gpu_instances():
    status = merge_ai_statuses(
        [
            AiStatus(
                ok=True,
                available_models=1,
                running_models=1,
                model_names=["qwen3coder-35b"],
                running_model_names=["qwen3coder-35b"],
            ),
            AiStatus(
                ok=True,
                available_models=1,
                running_models=1,
                model_names=["llama3.1-pro"],
                running_model_names=["llama3.1-pro"],
            ),
        ]
    )

    assert status.ok
    assert status.available_models == 2
    assert status.running_models == 2
    assert status.model_names == ["llama3.1-pro", "qwen3coder-35b"]
    assert status.running_model_names == ["qwen3coder-35b", "llama3.1-pro"]
