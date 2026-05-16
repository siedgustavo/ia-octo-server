from octofan_controller.nvidia import MOCK_NVIDIA_SMI, parse_nvidia_smi_csv


def test_parse_nvidia_smi_csv():
    status = parse_nvidia_smi_csv(MOCK_NVIDIA_SMI)
    assert status.ok
    assert len(status.gpus) == 2
    assert status.gpus[0].name == "NVIDIA GeForce RTX 3060"
    assert status.gpus[0].temperature_gpu_c == 36
    assert status.gpus[1].power_draw_watts == 10.2
