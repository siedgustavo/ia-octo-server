from octofan_controller.cli import MOCK_OUTPUT
from octofan_controller.config import DisplayConfig
from octofan_controller.display import render_display, resolve_display_title
from octofan_controller.llamacpp import LlamaCppStatus
from octofan_controller.parser import parse_controller_output


def test_display_is_20_by_8():
    lines = render_display(parse_controller_output(MOCK_OUTPUT), DisplayConfig(), 55, LlamaCppStatus(ok=True, running_models=1))
    assert len(lines) == 8
    assert len(lines[0]) <= 10
    assert all(len(line) == 20 for line in lines[1:])


def test_display_uses_big_title_area():
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(title="OCTOFAN AI"),
        55,
        LlamaCppStatus(ok=True, running_models=1),
    )
    assert lines[0] == "OCTOFAN AI"
    assert lines[1] == "".ljust(20)
    assert lines[2].strip() == "TPS n/a"


def test_display_title_uses_main_hostname_uppercase(monkeypatch):
    monkeypatch.setenv("OCTOFAN_DISPLAY_HOSTNAME", "aiworker.core.sied.ar")
    assert resolve_display_title(DisplayConfig(title=None)) == "AIWORKER"
