# Power cycling del servidor: decision final (2026-09-03)

**Estado: Plan B (corte por PS_ON con relay) ABANDONADO.** El power cycling del servidor
queda cubierto por dos caminos:

| Necesidad | Camino |
| --- | --- |
| Host colgado / GPU perdida / sshd muerto | Watchdog autonomo del firmware Octofan => pulso **RESET** de la placa (Plan A, cableado y probado) |
| Placa irreconocible o apagado sostenido | Corte de **220 V** con enchufe inteligente SmartLife/Tuya (Plan C) |
| Apagado normal | `poweroff` del SO (la mother hace su secuencia ATX; no interviene hardware) |

## Configuracion fisica final

- `PS_ON` del JATX: **puente directo a GND** (fuente siempre encendida por logico ATX).
- Plan A: **RST SW (PC3) -> RESET_SW del F_PANEL de la ZX directo**. Probado con
  `fan_controller_cli -x`: la maquina se resetea. El watchdog del firmware escala solo:
  sin alimento, timeout corto => pulso PC3 (reset de placa + auto-reset del AVR).
- La linea **PWR SW (PC4) queda sin usar**. Nunca conectarla al PWR_SW de la ZX: `-p`
  latchea cerrado y deja "boton presionado" hasta que muere el AVR.
- Enchufe inteligente sobre la alimentacion AC del gabinete.

**Requisitos para que el Plan C funcione (verificar ambos):**

1. Enchufe: `Power Recovery / estado tras corte de energia = ON` (muchos vienen en OFF o
   "recordar" por defecto).
2. BIOS de la ZX: `Restore on AC Power Loss = Power On`. Sin esto, cuando el enchufe
   vuelve, la fuente revive pero la placa queda en standby esperando boton.

Prueba corta: con el rig prendido, cortar 10 s desde el enchufe y devolver; tiene que
volver solo hasta el daemon.

## Por que se abandoono el Plan B (evidencia de banco, 2026-09-03)

El circuito probado: modulo relay activo-alto (S/-/+) con puente S-+, 5V del propio host,
y cierre a masa desde PWR SW (PC4) para activarlo. Resultado: apagaba, pero **la bloqueaba
a la ZX**: boton frontal muerto y sin retorno hasta corte de AC. Causa medida:

1. **Sobrecorriente del pin del AVR**: PC4 es una patita logica del ATmega324PB (~20 mA
   recomendado / 40 mA abs max). La bobina del modulo pide 50-90 mA. El driver no satura:
   la "masa" queda en 1-2 V, el modulo trabaja al borde de su tension de atraccion y
   **rebota**. Multi-flapping de PS_ON = lockup profundo de la placa. Con masa por cable
   directo (sin pasar por PC4) el corte es unico y limpio, y la placa se recupera.
2. **OFF demasiado corto**: la duracion del corte quedaba librada al brownout del AVR
   (lo que tarda en morir el 5V USB ~ 0.5-2 s). Con la fuente casi sin carga las rails
   ATX no se descargan en ese tiempo y la placa queda en brownout/limbo. Se considero
   supercap (0.47-1F + diodo + limitador) para garantizar 15-30 s de OFF, pero con el
   punto 1 pendiente el plan completo requeria PNP inversor + supercap + validaciones.
3. **Un "OFF sostenido" por controller es imposible con bobina alimentada desde el USB
   del propio host**: fuente off => muere USB => muere AVR => se libera PC4 => la fuente
   vuelve. `-p` es ciclicamente un power-cycle, nunca un apagado final. (Para OFF
   sostenido por hardware: mantener el controller vivo con alimentacion externa
   (powerbank) + `-p` => latch retenido => fuente off indefinida. Util solo para
   traslado/aislamiento.)

Registro de la escalera del firmware (firmware_09.hex): short timeout => pulso PC3 +
WDT del AVR; long timeout => latch PC4 alto, liberado solo en boot init. Con PWR SW sin
conectar, la escalada longa queda inofensiva por diseño.

## Historico: circuito que se probo (no usar como base)

```text
+5V USB (del host) ──┬── + del modulo ── S del modulo (puente activo-alto)
                     │
PWR SW (PC4) ────────┴── masa de activacion   [SOBRECARGA PC4: causa del fallo]
NC del relay ── entre PSON activo del JATX y GND
```

Variantes que quedaron documentadas pero no implementadas: PNP inversor (2N3906, base
10k pull-up a +5V, PWR SW a base) para respetar los 20 mA del pin, y supercap para el
OFF largo. Si algun dia se retoma, son los dos requisitos obligatorios, mas la prueba
critica de auto-arranque de la Fase 3 original.

## Estados del watchdog de software (referencia)

El daemon alimenta el watchdog del firmware cada `watchdog.feed_interval_seconds` mientras
`watchdog.checks` (TCP/HTTP/**SSH con validacion de banner**) esten sanos y la condicion
GPU (`watchdog.gpus_expected`) se cumpla. Ante fallo GPU con `gpu_recovery_enabled`,
primero reinicia los contenedores configurados
(`gpu_recovery_restart_containers`, via socket docker montado en el controller) durante
`gpu_recovery_grace_seconds`; si no se recupera, deja de alimentar y el firmware actua.
Existe modo mantenimiento (`POST /api/watchdog/maintenance`) que alimenta siempre, y
gracia de startup de 120 s para absorber flaps de red tras recreates de container.
