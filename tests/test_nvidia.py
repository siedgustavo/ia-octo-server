import subprocess

from octofan_controller.nvidia import MOCK_NVIDIA_SMI, NvidiaSmi, parse_nvidia_smi_csv


def test_parse_nvidia_smi_csv():
    status = parse_nvidia_smi_csv(MOCK_NVIDIA_SMI)
    assert status.ok
    assert len(status.gpus) == 2
    assert status.gpus[0].name == "NVIDIA GeForce RTX 3060"
    assert status.gpus[0].temperature_gpu_c == 36
    assert status.gpus[1].power_draw_watts == 10.2


def test_nvidia_smi_skips_unsupported_fields(monkeypatch):
    calls = []

    def fake_check_output(cmd, **kwargs):
        calls.append(cmd)
        query = cmd[1]
        if "decoder.stats.sessionCount" in query:
            raise subprocess.CalledProcessError(
                2,
                cmd,
                output='Field "decoder.stats.sessionCount" is not a valid field to query.\n',
            )
        return "0, GPU-test, NVIDIA Test, 00000000:02:00.0, 595.71.05, 94.00, 42, N/A, 0, 10, 1, 12288, 256, 12032, 40.50, 170.00, 300, 405, 1800, 7501, P8, Default, Disabled, 4, 4, 16, 16, 0\n"

    monkeypatch.delenv("OCTOFAN_MOCK", raising=False)
    monkeypatch.delenv("NVIDIA_SMI_MOCK", raising=False)
    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    status = NvidiaSmi().status()

    assert status.ok
    assert len(calls) == 2
    assert status.error == "Skipped unsupported nvidia-smi fields: decoder.stats.sessionCount"
    assert status.gpus[0].temperature_gpu_c == 42
    assert status.gpus[0].decoder_sessions is None
