import asyncio

from octofan_controller.config import RpcBackendConfig, RpcConfig
from octofan_controller.rpc import RpcMonitor, _decode_chunked


def test_rpc_monitor_reports_backend_up():
    async def run():
        server = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            cfg = RpcConfig(
                enabled=True,
                backends=[RpcBackendConfig(name="gpu0", gpu=0, target=f"127.0.0.1:{port}")],
            )
            status = await RpcMonitor().status(cfg)
        finally:
            server.close()
            await server.wait_closed()
        return status

    status = asyncio.run(run())

    assert status.ok
    assert status.up == 1
    assert status.total == 1


def test_rpc_monitor_reports_backend_down():
    cfg = RpcConfig(
        enabled=True,
        timeout_seconds=0.2,
        backends=[RpcBackendConfig(name="gpu0", gpu=0, target="127.0.0.1:1")],
    )

    status = asyncio.run(RpcMonitor().status(cfg))

    assert not status.ok
    assert status.up == 0
    assert status.total == 1
    assert status.backends[0].error


def test_decode_chunked_docker_response_body():
    assert _decode_chunked(b'8\r\n{"ok":1}\r\n0\r\n\r\n') == b'{"ok":1}'
