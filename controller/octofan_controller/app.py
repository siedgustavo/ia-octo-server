from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .cli import OctofanCli, percent_to_pwm
from .config import AppConfig, load_config, save_config
from .control import calculate_fan_control_decision, clamp_active_fan_percent
from .display import render_display, resolve_display_title
from .llamacpp import LlamaCppClient, LlamaCppStatus
from .metrics import metrics_payload, update_metrics
from .nvidia import NvidiaSmi, NvidiaStatus
from .parser import ControllerStatus
from .watchdog import run_watchdog_checks


CONFIG_PATH = Path(os.getenv("OCTOFAN_CONFIG", "/config/octofan.yaml"))
BIN_PATH = os.getenv("OCTOFAN_BIN", "/opt/octofan/fan_controller_cli")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [
        asyncio.create_task(poll_loop()),
        asyncio.create_task(watchdog_loop()),
        asyncio.create_task(display_loop()),
        asyncio.create_task(led_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Octofan AI Controller", version="0.1.0", lifespan=lifespan)
cli = OctofanCli(BIN_PATH)
llamacpp_client = LlamaCppClient()
nvidia_smi = NvidiaSmi()
state: dict[str, Any] = {
    "config": load_config(CONFIG_PATH),
    "status": ControllerStatus(ok=False, error="not polled yet"),
    "llamacpp": LlamaCppStatus(),
    "nvidia": NvidiaStatus(ok=False, gpus=[], error="not polled yet"),
    "target_fan": None,
    "fan_control": None,
    "applied_fan_target": None,
    "applied_fan_ids": [],
    "gpu_idle_since": None,
    "gpu_idle_stop_active": False,
    "eeprom_display_signature": None,
    "led_modes": {},
    "events": [],
    "watchdog": None,
}


class ManualFanRequest(BaseModel):
    percent: int


class DisplayRenderRequest(BaseModel):
    profile: str | None = None


async def poll_loop() -> None:
    while True:
        cfg: AppConfig = state["config"]
        status = cli.status()
        llamacpp = await llamacpp_client.status(cfg.llamacpp)
        nvidia = nvidia_smi.status()
        gpu_idle_stop_active = _gpu_idle_stop_active(cfg, status, nvidia, llamacpp)
        fan_control = calculate_fan_control_decision(
            status,
            cfg.fans,
            state["target_fan"],
            llamacpp.generating,
            gpu_idle_stop_active,
            nvidia,
        )
        target = fan_control.target_percent
        fan_ids = sorted(status.fans.keys()) if status.ok and status.fans else list(range(12))
        desired_pwm = percent_to_pwm(target)
        hardware_drifted = any(
            fan.current_pwm is not None and fan.current_pwm != desired_pwm
            for fan in status.fans.values()
        )
        if target != state["applied_fan_target"] or fan_ids != state["applied_fan_ids"] or hardware_drifted:
            try:
                cli.set_all_fans_percent(fan_ids, target)
                state["applied_fan_target"] = target
                state["applied_fan_ids"] = fan_ids
            except Exception as exc:
                _event(f"failed to set fans: {exc}")
        state.update(
            status=status,
            llamacpp=llamacpp,
            nvidia=nvidia,
            target_fan=target,
            fan_control=fan_control,
            gpu_idle_stop_active=gpu_idle_stop_active,
        )
        update_metrics(status, llamacpp, target, nvidia, fan_control)
        await asyncio.sleep(cfg.fans.poll_interval_seconds)


async def watchdog_loop() -> None:
    configured = False
    unhealthy_failures = 0
    while True:
        cfg: AppConfig = state["config"]
        if cfg.watchdog.enabled:
            if not configured:
                try:
                    cli.configure_watchdog(cfg.watchdog.short_timeout_seconds, cfg.watchdog.long_timeout_seconds)
                    configured = True
                except Exception as exc:
                    _event(f"failed to configure watchdog: {exc}")
            result = await run_watchdog_checks(cfg.watchdog)
            state["watchdog"] = result
            if result.healthy:
                unhealthy_failures = 0
                try:
                    cli.feed_watchdog()
                except Exception as exc:
                    _event(f"failed to feed watchdog: {exc}")
            else:
                unhealthy_failures += 1
                errors = ", ".join(result.errors)
                if _watchdog_in_grace_period(unhealthy_failures, cfg.watchdog.unhealthy_failures_before_reset):
                    _event(
                        "watchdog unhealthy "
                        f"({unhealthy_failures}/{cfg.watchdog.unhealthy_failures_before_reset}): {errors}"
                    )
                    try:
                        cli.feed_watchdog()
                    except Exception as exc:
                        _event(f"failed to feed watchdog during unhealthy grace period: {exc}")
                else:
                    _event(f"watchdog unhealthy: {errors}")
        else:
            configured = False
            unhealthy_failures = 0
            state["watchdog"] = None
            if cfg.watchdog.keepalive_when_disabled:
                try:
                    cli.feed_watchdog()
                except Exception as exc:
                    _event(f"failed to keep watchdog alive: {exc}")
        await asyncio.sleep(cfg.watchdog.feed_interval_seconds)


def _watchdog_in_grace_period(unhealthy_failures: int, threshold: int) -> bool:
    return unhealthy_failures < threshold


async def display_loop() -> None:
    while True:
        cfg: AppConfig = state["config"]
        if cfg.display.enabled:
            await _write_display(cfg.display.profile)
        await asyncio.sleep(cfg.display.refresh_interval_seconds)


async def led_loop() -> None:
    while True:
        cfg: AppConfig = state["config"]
        try:
            if cfg.leds.enabled:
                desired = _desired_led_modes(cfg, state["status"], state["llamacpp"], state["nvidia"])
                _apply_led_modes(desired)
        except Exception as exc:
            _event(f"failed to update leds: {exc}")
        await asyncio.sleep(cfg.leds.poll_interval_seconds)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return UI_HTML


@app.get("/metrics")
async def metrics() -> Response:
    return Response(metrics_payload(), media_type="text/plain; version=0.0.4")


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return serialize_status()


@app.get("/api/config")
async def api_config() -> dict[str, Any]:
    return state["config"].model_dump(mode="json")


@app.put("/api/config")
async def api_update_config(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = AppConfig.model_validate(payload)
    save_config(CONFIG_PATH, cfg)
    state["config"] = cfg
    _event("config updated")
    return cfg.model_dump(mode="json")


@app.post("/api/fans/manual")
async def api_fans_manual(req: ManualFanRequest) -> dict[str, Any]:
    cfg: AppConfig = state["config"]
    cfg.fans.mode = "manual"
    cfg.fans.manual_percent = clamp_active_fan_percent(req.percent, cfg.fans)
    save_config(CONFIG_PATH, cfg)
    state["config"] = cfg
    state["applied_fan_target"] = None
    state["applied_fan_ids"] = []
    try:
        status: ControllerStatus = state["status"]
        fan_ids = sorted(status.fans.keys()) if status.ok and status.fans else list(range(12))
        cli.set_all_fans_percent(fan_ids, cfg.fans.manual_percent)
        state["applied_fan_target"] = cfg.fans.manual_percent
        state["applied_fan_ids"] = fan_ids
    except Exception as exc:
        _event(f"failed to set manual fans: {exc}")
    _event(f"manual fan set to {cfg.fans.manual_percent}%")
    return {"ok": True, "percent": cfg.fans.manual_percent}


@app.post("/api/fans/auto")
async def api_fans_auto() -> dict[str, Any]:
    cfg: AppConfig = state["config"]
    cfg.fans.mode = "auto"
    save_config(CONFIG_PATH, cfg)
    state["config"] = cfg
    state["applied_fan_target"] = None
    state["applied_fan_ids"] = []
    _event("auto fan enabled")
    return {"ok": True}


@app.post("/api/display/render")
async def api_display_render(req: DisplayRenderRequest) -> dict[str, Any]:
    return {"ok": True, "lines": await _write_display(req.profile, force_eeprom=True)}


@app.post("/api/watchdog/test")
async def api_watchdog_test() -> dict[str, Any]:
    result = await run_watchdog_checks(state["config"].watchdog)
    return {"healthy": result.healthy, "checked": result.checked, "errors": result.errors}


@app.post("/api/calibrate-fans")
async def api_calibrate_fans() -> dict[str, Any]:
    status: ControllerStatus = state["status"]
    if not status.ok:
        raise HTTPException(503, "controller unavailable")
    for fan_id in sorted(status.fans.keys()):
        max_rpm = status.fans[fan_id].rpm or 0
        cli.set_fan_max_rpm(fan_id, max_rpm)
    _event("fan calibration saved from current RPM")
    return {"ok": True}


async def _write_display(profile: str | None, force_eeprom: bool = False) -> list[str]:
    cfg: AppConfig = state["config"]
    display_cfg = cfg.display.model_copy(update={"profile": profile or cfg.display.profile})
    lines = render_display(
        state["status"],
        display_cfg,
        state["target_fan"],
        state["llamacpp"],
        state["nvidia"],
    )
    try:
        signature = (resolve_display_title(display_cfg), display_cfg.profile)
        title_written = False
        if display_cfg.persist_to_eeprom and (force_eeprom or state["eeprom_display_signature"] != signature):
            cli.oled_text(0, 0, 4, "0")
            cli.oled_text(0, 0, 3, lines[0])
            title_written = True
            for y, line in enumerate(lines[2:], start=2):
                cli.oled_text(0, y, 2, line)
            state["eeprom_display_signature"] = signature

        for y, line in enumerate(lines):
            if y == 0:
                if not display_cfg.persist_to_eeprom and not title_written:
                    cli.oled_text(0, 0, 3, line)
            elif y == 1:
                continue
            else:
                cli.oled_text(0, y, 0, line)
    except Exception as exc:
        _event(f"failed to update display: {exc}")
    return lines


def serialize_status() -> dict[str, Any]:
    status: ControllerStatus = state["status"]
    watchdog = state["watchdog"]
    gpu_idle_since = state["gpu_idle_since"]
    return {
        "controller": {
            "ok": status.ok,
            "error": status.error,
            "serial": status.serial,
            "versions": {
                "cli": status.version_cli,
                "fw": status.version_fw,
                "hw": status.version_hw,
                "boot": status.version_boot,
            },
            "intake_temp_c": status.intake_temp_c,
            "exhaust_temp_c": status.exhaust_temp_c,
            "power_ac_total_w": status.power_ac_total_w,
        },
        "fans": {k: vars(v) for k, v in status.fans.items()},
        "psus": {k: vars(v) for k, v in status.psus.items()},
        "bme280": {k: vars(v) for k, v in status.bme280.items()},
        "watchdog": None if watchdog is None else vars(watchdog),
        "llamacpp": state["llamacpp"].to_dict(),
        "nvidia": state["nvidia"].to_dict(),
        "leds": {
            "enabled": state["config"].leds.enabled,
            "modes": dict(state["led_modes"]),
        },
        "target_fan_percent": state["target_fan"],
        "fan_control": vars(state["fan_control"]) if state["fan_control"] else None,
        "gpu_idle_seconds": None if gpu_idle_since is None else round(time.monotonic() - gpu_idle_since, 1),
        "gpu_idle_stop_active": state["gpu_idle_stop_active"],
        "events": state["events"][-50:],
    }


def _event(message: str) -> None:
    state["events"].append(message)
    state["events"] = state["events"][-200:]


def _desired_led_modes(
    cfg: AppConfig,
    status: ControllerStatus,
    llamacpp: LlamaCppStatus,
    nvidia: NvidiaStatus,
) -> dict[int, int]:
    leds = cfg.leds
    controlled_ids = {leds.warning_led_id, leds.online_led_id, leds.activity_led_id}
    desired = {led_id: leds.off_mode for led_id in controlled_ids}
    if llamacpp.ok:
        desired[leds.online_led_id] = leds.on_mode
    if _led_activity_active(cfg, nvidia):
        desired[leds.activity_led_id] = leds.fast_blink_mode
    if not status.ok or (cfg.llamacpp.enabled and not llamacpp.ok):
        desired[leds.warning_led_id] = leds.slow_blink_mode
    return desired


def _led_activity_active(cfg: AppConfig, nvidia: NvidiaStatus) -> bool:
    if not nvidia.ok:
        return False
    for gpu in nvidia.gpus:
        if (
            gpu.utilization_gpu_percent is not None
            and gpu.utilization_gpu_percent >= cfg.leds.gpu_activity_utilization_percent
        ):
            return True
        if gpu.power_draw_watts is not None and gpu.power_draw_watts >= cfg.leds.gpu_activity_power_watts:
            return True
    return False


def _apply_led_modes(desired: dict[int, int]) -> None:
    previous: dict[int, int] = state["led_modes"]
    for led_id, mode in sorted(desired.items()):
        if previous.get(led_id) == mode:
            continue
        cli.set_led(led_id, mode)
        previous[led_id] = mode
    for led_id in sorted(set(previous) - set(desired)):
        cli.set_led(led_id, state["config"].leds.off_mode)
        del previous[led_id]


def _gpu_idle_stop_active(
    cfg: AppConfig,
    status: ControllerStatus,
    nvidia: NvidiaStatus,
    llamacpp: LlamaCppStatus,
) -> bool:
    fans = cfg.fans
    now = time.monotonic()
    if not _gpu_idle_stop_candidate(cfg, status, nvidia, llamacpp):
        state["gpu_idle_since"] = None
        return False

    if state["gpu_idle_since"] is None:
        state["gpu_idle_since"] = now
    return now - state["gpu_idle_since"] >= fans.gpu_idle_stop_delay_seconds


def _gpu_idle_stop_candidate(
    cfg: AppConfig,
    status: ControllerStatus,
    nvidia: NvidiaStatus,
    llamacpp: LlamaCppStatus,
) -> bool:
    fans = cfg.fans
    intake_temp = status.intake_temp_c
    if (
        not fans.gpu_idle_stop_enabled
        or fans.mode != "auto"
        or not status.ok
        or intake_temp is None
        or intake_temp > fans.gpu_idle_max_intake_temp_c
        or llamacpp.generating
        or not nvidia.ok
        or not nvidia.gpus
    ):
        return False

    for gpu in nvidia.gpus:
        if gpu.temperature_gpu_c is None or gpu.temperature_gpu_c > fans.gpu_idle_max_gpu_temp_c:
            return False
        if gpu.utilization_gpu_percent is None or gpu.utilization_gpu_percent > fans.gpu_idle_utilization_percent:
            return False
        if gpu.power_draw_watts is None or gpu.power_draw_watts > fans.gpu_idle_power_watts:
            return False
        if (gpu.encoder_sessions or 0) > 0 or (gpu.decoder_sessions or 0) > 0:
            return False
    return True


UI_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Octofan AI Controller</title>
  <style>
    body{font-family:system-ui,Arial,sans-serif;margin:0;background:#111827;color:#e5e7eb}
    main{max-width:1120px;margin:0 auto;padding:24px}
    section{border-top:1px solid #374151;padding:18px 0}
    label{display:block;margin:10px 0 4px;color:#93c5fd}
    input,select,button{font:inherit;padding:8px;border-radius:6px;border:1px solid #4b5563;background:#1f2937;color:#fff}
    button{cursor:pointer;background:#2563eb;border-color:#2563eb;margin-top:12px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
    .metric{background:#1f2937;padding:14px;border-radius:8px}
    pre{white-space:pre-wrap;background:#0b1220;padding:12px;border-radius:8px}
  </style>
</head>
<body><main>
  <h1>Octofan AI Controller</h1>
  <section class="grid" id="metrics"></section>
  <section>
    <h2>Fans</h2>
    <label>Mode <select id="fanMode"><option>auto</option><option>manual</option></select></label>
    <div class="grid">
      <label>Min fan % <input id="minFan" type="number"></label>
      <label>Max fan % <input id="maxFan" type="number"></label>
      <label>Manual fan % <input id="manualFan" type="number"></label>
      <label>Intake ramp start C <input id="intakeStart" type="number" step="0.5"></label>
      <label>Intake full speed C <input id="intakeFull" type="number" step="0.5"></label>
      <label>Intake critical C <input id="intakeCritical" type="number" step="0.5"></label>
      <label>Exhaust ramp start C <input id="exhaustStart" type="number" step="0.5"></label>
      <label>Exhaust full speed C <input id="exhaustFull" type="number" step="0.5"></label>
      <label>Exhaust critical C <input id="exhaustCritical" type="number" step="0.5"></label>
      <label>GPU ramp start C <input id="gpuStart" type="number" step="0.5"></label>
      <label>GPU full speed C <input id="gpuFull" type="number" step="0.5"></label>
      <label>GPU critical C <input id="gpuCritical" type="number" step="0.5"></label>
    </div>
    <button onclick="saveConfig()">Save config</button>
    <button onclick="applyManualFan()">Apply manual fan</button>
    <button onclick="autoFan()">Auto mode</button>
  </section>
  <section>
    <h2>Display</h2>
    <label>Profile <select id="displayProfile"><option>ai</option><option>system</option><option>thermal</option><option>power</option></select></label>
    <button onclick="renderDisplay()">Render now</button>
    <pre id="display"></pre>
  </section>
  <section>
    <h2>Watchdog</h2>
    <label><input id="watchdogEnabled" type="checkbox"> Enabled</label>
    <label>Check target <input id="watchdogTarget"></label>
    <button onclick="saveConfig()">Save config</button>
    <button onclick="testWatchdog()">Test watchdog</button>
    <pre id="watchdog"></pre>
  </section>
  <section>
    <h2>Raw status</h2><pre id="raw"></pre>
  </section>
</main>
<script>
let cfg={}
async function refresh(){
  cfg=await (await fetch('/api/config')).json()
  const st=await (await fetch('/api/status')).json()
  fanMode.value=cfg.fans.mode; minFan.value=cfg.fans.min_percent
  maxFan.value=cfg.fans.max_percent; manualFan.value=cfg.fans.manual_percent
  intakeStart.value=cfg.fans.intake_ramp_start_c; intakeFull.value=cfg.fans.intake_full_speed_c; intakeCritical.value=cfg.fans.intake_critical_c
  exhaustStart.value=cfg.fans.exhaust_ramp_start_c; exhaustFull.value=cfg.fans.exhaust_full_speed_c; exhaustCritical.value=cfg.fans.exhaust_critical_c
  gpuStart.value=cfg.fans.gpu_ramp_start_c; gpuFull.value=cfg.fans.gpu_full_speed_c; gpuCritical.value=cfg.fans.gpu_critical_c
  displayProfile.value=cfg.display.profile; watchdogEnabled.checked=cfg.watchdog.enabled
  watchdogTarget.value=(cfg.watchdog.checks[0]||{target:'host.docker.internal:22'}).target
  metrics.innerHTML=[
    ['Controller', st.controller.ok?'OK':'DOWN'],
    ['Intake', st.controller.intake_temp_c+' C'],
    ['Exhaust', st.controller.exhaust_temp_c+' C'],
    ['Target fan', st.target_fan_percent+' %'],
    ['Fan policy', st.fan_control ? st.fan_control.reason+' ('+st.fan_control.raw_target_percent+' % demand)' : '--'],
    ['Power', st.controller.power_ac_total_w+' W'],
    ['llama.cpp', st.llamacpp.available_models+' available / '+st.llamacpp.running_models+' generating'],
    ['AI activity', (st.nvidia.gpus||[]).some(g=>g.utilization_gpu_percent>=cfg.leds.gpu_activity_utilization_percent || g.power_draw_watts>=cfg.leds.gpu_activity_power_watts) ? 'GPU active' : 'idle'],
    ['LEDs', st.leds.enabled ? JSON.stringify(st.leds.modes) : 'disabled'],
    ['GPUs', (st.nvidia.gpus||[]).length],
    ['GPU temp', (st.nvidia.gpus||[]).map(g=>g.temperature_gpu_c+' C').join(' / ') || '--']
  ].map(([k,v])=>`<div class="metric"><b>${k}</b><br>${v}</div>`).join('')
  raw.textContent=JSON.stringify(st,null,2)
}
async function saveConfig(){
  cfg.fans.mode=fanMode.value
  cfg.fans.min_percent=parseInt(minFan.value); cfg.fans.max_percent=parseInt(maxFan.value); cfg.fans.manual_percent=parseInt(manualFan.value)
  cfg.fans.intake_ramp_start_c=parseFloat(intakeStart.value); cfg.fans.intake_full_speed_c=parseFloat(intakeFull.value); cfg.fans.intake_critical_c=parseFloat(intakeCritical.value)
  cfg.fans.exhaust_ramp_start_c=parseFloat(exhaustStart.value); cfg.fans.exhaust_full_speed_c=parseFloat(exhaustFull.value); cfg.fans.exhaust_critical_c=parseFloat(exhaustCritical.value)
  cfg.fans.gpu_ramp_start_c=parseFloat(gpuStart.value); cfg.fans.gpu_full_speed_c=parseFloat(gpuFull.value); cfg.fans.gpu_critical_c=parseFloat(gpuCritical.value)
  cfg.display.profile=displayProfile.value; cfg.watchdog.enabled=watchdogEnabled.checked
  cfg.watchdog.checks=[{type: watchdogTarget.value.startsWith('http')?'http':'tcp', target: watchdogTarget.value, timeout_seconds:1}]
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)})
  refresh()
}
async function applyManualFan(){await fetch('/api/fans/manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({percent:parseInt(manualFan.value)})}); refresh()}
async function autoFan(){await fetch('/api/fans/auto',{method:'POST'}); refresh()}
async function renderDisplay(){const r=await (await fetch('/api/display/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:displayProfile.value})})).json(); display.textContent=r.lines.join('\\n')}
async function testWatchdog(){watchdog.textContent=JSON.stringify(await (await fetch('/api/watchdog/test',{method:'POST'})).json(),null,2)}
refresh(); setInterval(refresh,5000)
</script></body></html>
"""
