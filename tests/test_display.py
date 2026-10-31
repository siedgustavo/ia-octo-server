from octofan_controller.cli import MOCK_OUTPUT
from octofan_controller.config import DisplayConfig
from octofan_controller.display import render_display, resolve_display_title, resolve_host_ip
from octofan_controller.llamacpp import LlamaCppStatus
from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.ollama import OllamaStatus
from octofan_controller.parser import parse_controller_output
from octofan_controller.strata import StrataStatus


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
        NvidiaStatus(
            ok=True,
            gpus=[GpuStatus(index=0, uuid="GPU-0", name="RTX", pci_bus_id="01:00.0", temperature_gpu_c=41, utilization_gpu_percent=17)],
        ),
    )
    assert lines[0] == "OCTOFAN AI"
    assert lines[1] == "".ljust(20)
    assert lines[2].strip().startswith("IP ")
    assert lines[3].strip() == "AI services OK"
    assert lines[4].strip() == "GPU 41C Load 17%"
    assert lines[5].strip() == "In 32C Fan 55%"
    assert lines[6].strip().startswith("Power ")


def test_display_does_not_report_degraded_ai_when_legacy_monitor_is_disabled():
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(profile="ai"),
        10,
        LlamaCppStatus(),
    )

    assert lines[3].strip() == "AI monitor off"


def test_display_ai_line_prefers_strata_and_shows_loaded_models():
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(profile="ai"),
        10,
        LlamaCppStatus(),
        ollama=OllamaStatus(enabled=True, up=False),
        strata=StrataStatus(enabled=True, up=True, total_models=1, loaded_models=1),
    )

    assert lines[3].strip() == "Strata 1/1 loaded"


def test_display_ai_line_reports_strata_down_over_stopped_ollama():
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(profile="ai"),
        10,
        LlamaCppStatus(),
        ollama=OllamaStatus(),
        strata=StrataStatus(enabled=True, up=False),
    )

    assert lines[3].strip() == "Strata DOWN"


def test_display_ai_line_falls_back_to_ollama_when_strata_is_disabled():
    lines = render_display(
        parse_controller_output(MOCK_OUTPUT),
        DisplayConfig(profile="ai"),
        10,
        LlamaCppStatus(),
        ollama=OllamaStatus(enabled=True, up=True, running_models=2),
        strata=StrataStatus(),
    )

    assert lines[3].strip() == "Ollama 2 loaded"


def test_display_title_uses_main_hostname_uppercase(monkeypatch):
    monkeypatch.setenv("OCTOFAN_DISPLAY_HOSTNAME", "aiworker.core.sied.ar")
    assert resolve_display_title(DisplayConfig(title=None)) == "AIWORKER"


def test_display_ip_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("OCTOFAN_DISPLAY_IP", "172.16.1.40")
    assert resolve_host_ip() == "172.16.1.40"
