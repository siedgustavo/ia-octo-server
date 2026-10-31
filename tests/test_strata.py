import asyncio

import httpx

from octofan_controller.strata import StrataClient, parse_strata_models

MODELS_PAYLOAD = {
    "object": "list",
    "data": [
        {
            "id": "huihui-qwen3.8-flash-next-abliterated-v2-ud-q4_k_xl",
            "object": "model",
            "status": {"value": "loaded"},
            "meta": {"n_ctx": 262144},
        },
        {"id": "other-model", "object": "model", "status": {"value": "unloaded"}},
    ],
}


def test_parse_strata_models_flags_loaded_state():
    models = parse_strata_models(MODELS_PAYLOAD)

    assert [model.id for model in models] == [
        "huihui-qwen3.8-flash-next-abliterated-v2-ud-q4_k_xl",
        "other-model",
    ]
    assert models[0].loaded
    assert models[0].context_size == 262144
    assert not models[1].loaded


def test_parse_strata_models_tolerates_garbage():
    assert parse_strata_models(None) == []
    assert parse_strata_models({"data": "nope"}) == []


def strata_client(handler) -> StrataClient:
    return StrataClient(transport=httpx.MockTransport(handler))


def test_strata_client_disabled_does_not_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled client must not request")

    status = asyncio.run(strata_client(handler).status("http://strata:8080", False, 2.0))

    assert not status.enabled
    assert not status.up
    assert status.error is None


def test_strata_client_counts_loaded_models():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=MODELS_PAYLOAD)

    status = asyncio.run(strata_client(handler).status("http://strata:8080/", True, 2.0))

    assert seen["url"] == "http://strata:8080/v1/models"
    assert status.up
    assert status.total_models == 2
    assert status.loaded_models == 1
    assert status.error is None


def test_strata_client_reports_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    status = asyncio.run(strata_client(handler).status("http://strata:8080", True, 2.0))

    assert not status.up
    assert "connection refused" in status.error
