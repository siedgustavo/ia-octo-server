# Hardware Mods

Estado fisico actual del gabinete Octominer/Octofan tras la conversion a servidor IA.

## Placa madre actual

- Placa original del Octominer: **retirada**. Ya no existe dentro del gabinete.
- Placa instalada: **ZX-DU99D4 V1.41** (dual socket LGA2011-3, chipset X99, doble Intel
  Xeon E5 v3/v4, 8x DDR4 ECC, BIOS AMI).
- Alimentacion de la placa nueva (distribucion):
  - **Pico ATX de 120 W**: se alimenta desde el rail de 12 V del backplane de la fuente
    del Octominer y entrega al conector ATX principal de la placa solo logica, RAM, NVMe,
    USB y chipset. No alimenta los CPU.
  - **EPS 8 pines directo desde la fuente del Octominer**: alimenta los VRM de los dos
    Xeon. Los procesadores no pasan por la pico ATX.

## Fuente del Octominer (always-on)

- El conector JATX del backplane de la fuente original llevaba `PS_ON` hacia la placa del
  Octominer. Al no existir esa placa, se hizo un **puente fisico `PS_ON`-`GND`** en el
  lado del conector.
- Consecuencia: la fuente del Octominer queda **siempre encendida**. Sus rails (12 V hacia
  la pico ATX, **EPS 8 pines hacia los CPU**, 12 V hacia los fans/LED del gabinete) estan
  activos permanentemente.

## Impacto en el control por firmware

- El relé/watchdog del firmware del Octofan **ya no puede cortar ni encender la fuente**.
  En el diseno original del minero el firmware controlaba el arranque via `PS_ON`; con el
  puente eso desaparecio.
- El watchdog configurado (`watchdog.checks` TCP a `host.docker.internal:22`) hoy solo
  provoca el **reset USB del controller** (desconecta/reconecta el controlador cada
  ~504 s si no se alimenta). **No** es un power cycle real de la placa Xeon.
- El ciclo de encendido/apagado de la placa pasa a ser responsabilidad del propio Xeon
  (AC power, boton/reset de la placa, o `shutdown` del SO). No hay power cycling remoto
  por hardware; para reinicios remotos usar `reboot`/`poweroff` por SSH.

## Presupuesto de energia

- Pico ATX: 120 W maximos en 12 V, pero solo para logica + RAM + NVMe + USB (sin CPU).
- Los dos Xeon van por **EPS 8 pines directo a la fuente del Octominer**, asi que el TDP
  de los CPU no consume la pico ATX; el limite real es el rail de 12 V de la fuente
  original compartido con GPUs, fans y la propia pico.
- El EPS sale de la misma fuente cuyo `PS_ON` esta puenteado: un eventual control de
  `PS_ON` por watchdog cortaria **tambien** los CPU (power cycle completo de la placa).

## Verificacion rapida

- Fans y LED del gabinete siguen controlados por el controller USB (`16c0:05dc`) como
  siempre; eso no cambio.
- La fuente original entrega 12 V permanente: comprobar con multimetro en el JATX si se
  interviene el puente.

## Referencias del controller Octofan (investigacion 2026-08-30)

No existe pinout publicado del arnes RESET/POWER del controller en ningun sitio (HiveOS KB,
octominer.com, foros, r/octominer). La conversion de placa en el case es una pregunta
recurrente sin respuesta documentada; la gente resuelve el power cycle con enchufes WiFi.

- Repo oficial con el CLI y el firmware AVR del controller (reflasheable via modo
  bootloader `-bx` con `avrdude.conf`):
  `https://github.com/minershive/hiveos-linux/tree/master/hive/opt/octofan`
- Opcodes USB del protocolo (extraidos del debug info del `fan_controller_cli` local,
  no stripped): `USB_RESET_WATCHDOG=0`, `USB_READ_WATCHDOG=6`, `USB_WRITE_WATCHDOG=7`,
  `USB_RESET_RIG=145` (`-x`), `USB_POWERDOWN_RIG=146` (`-p`). El firmware acciona un GPIO
  del AVR al recibirlos; ese GPIO se puede rastrear desensamblando `firmware_09.hex` o
  con multimetro sobre el conector.
- El CLI original es de "C_Payne" (2019); el usuario `segmond` de r/octominer lo documenta
  en Ubuntu para LLMs (hilo "160GB of VRAM for $1000") con el mismo enfoque que este repo.

## Ingenieria inversa del firmware (firmware_09.hex, 2026-08-31)

Desassembly de `firmware_09.hex` (avr-objdump, `-m avr5`; binario en
`/tmp/opencode/octofan-fw/firmware_09.asm`). MCU confirmado: **ATmega324PB**
(`avrdude -pm324pb -cusbasp`, visto en el script `octofan` original). USB por bit-banging
estilo V-USB (VID:PID `16c0:05dc`) sobre PORTD; PD1 maneja attach/detach del pull-up.

### Senales de control de la placa (lo importante)

El dispatch de comandos USB esta en flash `0x224a`:

| Senal | Pin | Evidencia | Semantica |
| --- | --- | --- | --- |
| **RESET rig** | **PORTC.3 (PC3)**, activo alto, salida | handler `0x272c` (`-x`/145) y escalada short del watchdog `0x209e` | Pulso de ~0.3 s (delay SW de ~1.2M iteraciones) y despues el AVR **se auto-resetia via WDT** (secuencia `0x18`/`0x0C` en `WDTCR` + `wdr`) para re-enumerar USB limpio. Emula el boton RESET SW de la placa. |
| **POWER rig** | **PORTC.4 (PC4)**, activo alto, salida | handler `0x2768` (`-p`/146) y escalada long del watchdog `0x205a` | Se **pone alto y queda latcheado**: no hay ningun `cbi` de PC4 en el firmware. La unica liberacion esta en el **boot init** (`0x16de`/`0x16e0` limpia PC3 y PC4). |

- Los unicos `cbi PORTC,3` existen (reset si es pulso); PC4 solo se limpia al arrancar el AVR.
- Escalada del watchdog del firmware (main loop): **short timeout** = pulso PC3 + auto-reset
  del AVR; **long timeout** = latch PC4 alto.
- Otros GPIO: PC5/PC6/PC7 y PE3 son salidas puestas en alto al boot (`0x74b6`), presumibles
  LEDs/habilitaciones; PIND.3 la lee el ISR de USB.

### La pregunta del power cycle: ":lo vuelve a encender?"

Segun el codigo, **no existe en el firmware un pulso de PC4 "off y luego on"**: `-p` latchea
PC4 alto y ahi queda hasta que el controller se reinicia. La semantica encaja con dos
cableados posibles del arnes original, que hay que distinguir con multimetro en el board:

1. **PC4 en paralelo al PWR_SW de la placa**: mantenido alto = boton presionado (apagado
   forzodo a los ~4 s). Al no soltarse jamas, la placa no vuelve sola; el encendido original
   del minero dependeria de que el AVR se resetee (libera PC4) + comportamiento de la placa.
2. **PC4 como colector abierto sobre PS_ON de la fuente** (Latch estilo minero): PC4 alto =
   mantiene PS_ON bajo = rig apagado; PC4 liberado (o al arrancar el AVR) = la fuente entrega
   y la placa del minero arranca sola porque no tiene boton. Esto explicaria el diseno.

Prueba definitoria en el gabinete (con el puente PS_ON del JATX todavia puesto, la placa
Xeon no se ve afectada): medir continuidad entre la linea PC4 del arnes y el pin verde
(PS_ON) del conector ATX vs. el header PWR_SW. Si va a PS_ON, al sacar USB del controller
la fuente deberia encender: ahi el watchdog revive con power cycle real sin tocar nada mas.

### Otros hallazgos

- Bootloader en la seccion alta con banner ASCII "BOOTLOADER"; entrada `147` (`-bx` sale
  via reset), detach/attach USB forzodo manipulando DDRD.1/PORTD.1 antes de saltar a 0.
- El init imprime "INIT OLED!" y versiones de Hardware/Firmware/Bootloader; el modo `-t`
  corre tests de fans/temp/PSU con strings "TEST PASS/FAIL".
- Los sensores/PSU se leen por un periférico I2C/SMBus bit-bang (handler en `0x794a+`).

