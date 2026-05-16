from octofan_controller.cli import MOCK_OUTPUT
from octofan_controller.config import DisplayConfig
from octofan_controller.display import render_display
from octofan_controller.ollama import OllamaStatus
from octofan_controller.parser import parse_controller_output


def test_display_is_20_by_8():
    lines = render_display(parse_controller_output(MOCK_OUTPUT), DisplayConfig(), 55, OllamaStatus(ok=True, running_models=1))
    assert len(lines) == 8
    assert all(len(line) == 20 for line in lines)


def test_display_repeats_title_on_first_two_lines():
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(title="OCTOFAN AI"),
        55,
        OllamaStatus(ok=True, running_models=1),
    )
    assert lines[0] == "OCTOFAN AI".ljust(20)
    assert lines[1] == "OCTOFAN AI".ljust(20)
