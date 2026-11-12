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


def _fake_gpu_sysfs(tmp_path, address, device_id, raw):
    from octofan_controller.nvidia import GDDR6X_TEMP_OFFSET

    device_dir = tmp_path / address
    device_dir.mkdir()
    (device_dir / "device").write_text(f"0x{device_id:04x}\n")
    bar0 = bytearray(GDDR6X_TEMP_OFFSET + 0x1000)
    bar0[GDDR6X_TEMP_OFFSET:GDDR6X_TEMP_OFFSET + 4] = raw.to_bytes(4, "little")
    (device_dir / "resource0").write_bytes(bytes(bar0))


def test_read_vram_temperature_from_bar0(tmp_path):
    from octofan_controller.nvidia import read_vram_temperature

    _fake_gpu_sysfs(tmp_path, "0000:03:00.0", 0x2204, 0x80008580)

    assert read_vram_temperature("00000000:03:00.0", str(tmp_path)) == 44.0


def test_read_vram_temperature_ignores_other_devices_and_dead_gpus(tmp_path):
    from octofan_controller.nvidia import read_vram_temperature

    _fake_gpu_sysfs(tmp_path, "0000:02:00.0", 0x2504, 0x80008580)  # RTX 3060, GDDR6
    _fake_gpu_sysfs(tmp_path, "0000:03:00.0", 0x2204, 0xFFFFFFFF)  # fell off the bus

    assert read_vram_temperature("00000000:02:00.0", str(tmp_path)) is None
    assert read_vram_temperature("00000000:03:00.0", str(tmp_path)) is None
    assert read_vram_temperature("00000000:09:00.0", str(tmp_path)) is None
    assert read_vram_temperature("garbage", str(tmp_path)) is None


def test_fill_vram_temperatures_keeps_nvidia_smi_value(tmp_path):
    from octofan_controller.nvidia import fill_vram_temperatures

    _fake_gpu_sysfs(tmp_path, "0000:02:00.0", 0x2204, 0x80000C80)  # 100 C
    _fake_gpu_sysfs(tmp_path, "0000:03:00.0", 0x2204, 0x80000C80)
    status = parse_nvidia_smi_csv(MOCK_NVIDIA_SMI)
    status.gpus[1].temperature_memory_c = 70.0

    fill_vram_temperatures(status, str(tmp_path))

    assert status.gpus[0].temperature_memory_c == 100.0
    assert status.gpus[1].temperature_memory_c == 70.0
