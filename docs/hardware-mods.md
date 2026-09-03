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

- El conector **JATX** del backplane de la fuente original es de 6 hilos:

  ```text
  5VSB - SVSB - PSON - PSON - GND - GND
  ```

  (`SVSB` = sense de 5VSB; el `PSON` viene duplicado.)
- Ese cable llevaba `PS_ON` hacia la placa del Octominer, entrando al mismo header donde
  lo hacia el arnes del controller (por eso el boton del controller encendia el rig).
- Al no existir esa placa, se hizo un **puente fisico de UNO de los `PSON` a `GND`** en el
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

## Conector del controller (silkscreen impreso en la placa)

```text
┌────────────────────────────────────────────────────────────┐
│ 5V  USB+ USB- GND NC │ 5V  USB+ USB- GND PWR SW │
│ 5V  USB+ USB- GND NC │ 5V  USB+ USB- GND RST SW │
└────────────────────────────────────────────────────────────┘
```

- Cada fila es un puerto USB-A completo (`5V USB+ USB- GND`) + un pin `NC` + un header de
  2 pines de boton: **PWR SW** (fila superior) y **RST SW** (fila inferior).
- Coincide exacto con la ingenieria inversa del firmware: `PC3` = pulso ~0.3 s = **RST SW**;
  `PC4` = latch power-down = **PWR SW**.
- Los pares USB de este conector son como el controller se alimentaba/comunicaba con la
  mother del minero (por eso JATX y arnes entraban "al mismo lugar").
- Plan A (reset): el header **RST SW** va al `RESET_SW` del F_PANEL de la ZX-DU99D4
  **directo** (verificado 2026-08-31: ambas lineas son 3.3 V con pull-up y "presionar" =
  cierre a GND; no hace falta transistor ni R serie).
- Plan B (power): **ABANDONADO 2026-09-03** (`docs/watchdog-power-cycle.md`). La linea
  **PWR SW queda sin usar**: nunca al PWR_SW de la ZX (con `-p` latcheado quedaria
  "boton presionado para siempre" y la placa no rearanca sola).
- Estado cableado final (2026-09-03): **RST SW -> RESET_SW de la ZX conectado y probado**
  (`fan_controller_cli -x` resetea la maquina; el watchdog autonomo del firmware usa la
  misma linea en su escalada de timeout corto). `PS_ON` del JATX: puente directo. El
  apagado/ciclo AC queda en un enchufe inteligente SmartLife/Tuya.

## Limite de corriente de los headers PC3/PC4 (2026-09-03)

PC3/PC4 son patitas logicas del ATmega324PB: **~20 mA recomendado / 40 mA abs max** por
pin. Consecuencias medidas:

- Un modulo relay comun (bobina 50-90 mA) **no se puede colgar directo** de PWR SW: el
  driver no satura, la "masa" queda en 1-2 V, el modulo vibra al borde de su tension de
  atraccion y el multiple flap de la senal (en nuestro test, PS_ON) lockupeo la placa ZX
  (boton muerto hasta corte de AC).
- Para manejar carga desde estos headers hace falta una etapa de potencia (PNP 2N3906 /
  BC557 con base 10k pull-up, o relay de senal de <= 20 mA de bobina).
- RST SW no tiene este problema: no se le cuelga carga, solo el contacto del boton.

## Enlace I2C controller <-> backplane de la fuente

Hay un cuarto vinculo fisico ademas de USB, JATX y PWR/RST SW. Del lado del backplane de
la fuente esta rotulado:

```text
SGND  3.3V  SCL  SDA
```

- Es el bus por donde el controller **lee las fuentes** (el handler I2C/SMBus bit-bang que
  aparece en el firmware en `0x794a+`): voltajes, corrientes, temperaturas y energia que
  despues el CLI muestra como `OCTO-2000W PSU ... Vac/Iac/Pac/Vdc/Idc/T1/T2/T3` y
  `PSMI(DPS1200-compat.)` (metricas PSMI/PMBUS compatibles).
- Logica a **3.3 V** con `SGND` (signal ground, separado del GND de potencia).
- Implicacion practica: las metricas de PSU de Prometheus/Grafana dependen de este bus y de
  las fuentes originales del Octominer. Si algin dia se cambian por ATX comunes, se pierde
  telemetria de fuente (el controller seguira reportando fans/temp/OLED normal).
- No interviene en el Plan B: es solo telemetria, no control de power.

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
PC4 alto y ahi queda hasta que el controller se reinicia. El silkscreen del header lo llama
**PWR SW** (emulacion de boton), pero el latch permanente indica que en la mother del minero
esa linea no iba a un power-button logico sino al **net de PS_ON** (cerrar = ON / abrir =
OFF, como en las placas mineras sin boton). Tambien encaja con que el rig encendiera con el
boton del controller.

### Medicion empírica de los headers (2026-08-31)

Controller alimentado por USB independiente, multimetro en DC sobre los headers rotulados
(el silkscreen esta **correcto**; la confusion inicial fue leerlo al reves):

| Header | idle | Durante el comando | Veredicto |
| --- | --- | --- | --- |
| **PWR SW** (PC4) | alta impedancia ("boton soltado") | `-p`: **cierre a GND persistente** (latch) | **contacto seco activo-bajo**, exacto al firmware. Auto-liberacion al morir el AVR. |
| **RST SW** (PC3) | **3.3 V** (pull-up) | `-x`: pulso corto hacia GND (el tester alcanzo a marcar 2.8 V por refresco; confirmar con reset real sobre la placa) | emulacion de boton reset 3.3 V activo-bajo. |

Consecuencias directas:

- **Plan A**: RST SW va **directo** al `RESET_SW` de la ZX (mismo nivel 3.3 V, misma
  semantica "corto a GND = presionado"). No hace falta transistor.
- **Plan B**: PWR SW es un contacto a masa con auto-liberacion => modulo relay de
  **trigger activo-bajo** con el contacto entre `IN` y `GND` del modulo; cae la seccion de
  inversores NPN del doc de power-cycle.

### Otros hallazgos

- Bootloader en la seccion alta con banner ASCII "BOOTLOADER"; entrada `147` (`-bx` sale
  via reset), detach/attach USB forzodo manipulando DDRD.1/PORTD.1 antes de saltar a 0.
- El init imprime "INIT OLED!" y versiones de Hardware/Firmware/Bootloader; el modo `-t`
  corre tests de fans/temp/PSU con strings "TEST PASS/FAIL".
- Los sensores/PSU se leen por un periférico I2C/SMBus bit-bang (handler en `0x794a+`): es
  el enlace I2C `SGND/3.3V/SCL/SDA` del backplane de la fuente (ver seccion arriba).

