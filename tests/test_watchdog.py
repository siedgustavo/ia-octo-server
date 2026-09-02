from octofan_controller.nvidia import GpuStatus, NvidiaStatus
from octofan_controller.watchdog import gpu_watchdog_errors


def _gpus(count: int, phantoms: int = 0) -> list[GpuStatus]:
    gpus = [GpuStatus(index=i, uuid=f"GPU-{i}", name="RTX", pci_bus_id=f"0{i}:00.0") for i in range(count)]
    gpus += [GpuStatus(index=count + i, uuid="", name="", pci_bus_id="") for i in range(phantoms)]
    return gpus


def test_gpu_watchdog_disabled_when_not_expected():
    assert gpu_watchdog_errors(NvidiaStatus(ok=False, gpus=[], error="boom"), 0) == []


def test_gpu_watchdog_ok_with_expected_count():
    assert gpu_watchdog_errors(NvidiaStatus(ok=True, gpus=_gpus(4)), 4) == []


def test_gpu_watchdog_detects_lost_gpu():
    errors = gpu_watchdog_errors(NvidiaStatus(ok=True, gpus=_gpus(3)), 4)
    assert errors == ["expected 4 GPUs, nvidia-smi reports 3"]


def test_gpu_watchdog_detects_phantom_entry():
    nvidia = NvidiaStatus(ok=True, gpus=_gpus(4, phantoms=1))
    errors = gpu_watchdog_errors(nvidia, 4)
    assert any("without UUID" in e for e in errors)


def test_gpu_watchdog_detects_nvidia_smi_failure():
    nvidia = NvidiaStatus(ok=False, gpus=[], error="timeout")
    assert gpu_watchdog_errors(nvidia, 4) == ["nvidia-smi failed: timeout"]
