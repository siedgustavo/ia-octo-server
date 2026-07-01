from octofan_controller.cli import MOCK_OUTPUT
from octofan_controller.config import DisplayConfig
from octofan_controller.display import render_display, resolve_display_title
from octofan_controller.parser import parse_controller_output
from octofan_controller.rpc import RpcBackendStatus, RpcStatus


def test_display_is_20_by_8():
    lines = render_display(parse_controller_output(MOCK_OUTPUT), DisplayConfig(), 55, RpcStatus())
    assert len(lines) == 8
    assert len(lines[0]) <= 10
    assert all(len(line) == 20 for line in lines[1:])


def test_display_uses_big_title_area():
    rpc = RpcStatus(
        ok=True,
        backends=[
            RpcBackendStatus(name="gpu0", gpu=0, target="llamacpp-rpc-gpu0:5000", ok=True),
            RpcBackendStatus(name="gpu1", gpu=1, target="llamacpp-rpc-gpu1:5001", ok=True),
        ],
    )
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(title="OCTOFAN AI"),
        55,
        rpc,
    )
    assert lines[0] == "OCTOFAN AI"
    assert lines[1] == "".ljust(20)
    assert lines[2].strip() == "RPC OK"
    assert lines[3].strip() == "Backends 2/2"


def test_display_title_uses_main_hostname_uppercase(monkeypatch):
    monkeypatch.setenv("OCTOFAN_DISPLAY_HOSTNAME", "aiworker.core.sied.ar")
    assert resolve_display_title(DisplayConfig(title=None)) == "AIWORKER"
