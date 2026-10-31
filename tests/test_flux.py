import asyncio

import httpx

from octofan_controller.flux import FluxClient


def flux_client(handler) -> FluxClient:
    return FluxClient(transport=httpx.MockTransport(handler))


def test_flux_client_disabled_does_not_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled client must not request")

    status = asyncio.run(flux_client(handler).status("http://flux:1234", False, 2.0))

    assert not status.enabled
    assert not status.up


def test_flux_client_accepts_web_ui_as_health():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, text="<html></html>")

    status = asyncio.run(flux_client(handler).status("http://flux:1234/", True, 2.0))

    assert seen["url"] == "http://flux:1234/"
    assert status.up
    assert status.error is None


def test_flux_client_marks_server_errors_down():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    status = asyncio.run(flux_client(handler).status("http://flux:1234", True, 2.0))

    assert not status.up
    assert status.error == "HTTP 503"


def test_flux_client_marks_connection_errors_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    status = asyncio.run(flux_client(handler).status("http://flux:1234", True, 2.0))

    assert not status.up
    assert "connection refused" in status.error
