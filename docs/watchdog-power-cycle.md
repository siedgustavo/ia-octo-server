# Watchdog Plan B: power cycle real via PC4

Objetivo: que el long timeout del firmware del Octofan apague y vuelva a encender la fuente
del Octominer (power cycle completo: EPS de los Xeon, pico ATX, todo), sin electronica
exotica y con default **ON** a prueba de controller muerto.

## Logica de diseno

La mother del minero hacia de intermediaria: PS_ON del JATX llegaba a su header y su
circuito de power-button (manejado por el controller) lo llevaba a GND. Sin mother, la
emulamos:

```
PS_ON (JATX) ----[contacto NC del relay]---- GND     <- default ON (equivale al puente actual)
Relay: bobina alimentada con USB-5V del host, en serie con NPN, base al pin **PWR SW** del
conector del controller (= PC4) via 1k + 10k pull-down
```

| Estado | PC4 | USB 5V | Relay | PS_ON | Fuente |
| --- | --- | --- | --- | --- | --- |
| Host sano (normal) | low | presente | suelto | GND | ON |
| Long timeout dispara | **high** | presente | atraido | flotante | **OFF** |
| Fuente apagada => host off | (perdido) | **ido** | suelto | GND | **ON de nuevo** |
| Controller desenchufado / frito | - | - | suelto | GND | ON |

Resultado: el long timeout produce un **apagon de ~10-30 s y re-encendido automatico**.
Si el host vuelve y el daemon alimenta el watchdog, el ciclo se detiene. Si el host esta
muerto del todo, el rig queda en ciclo off/on lento (comportamiento esperado de un rig
headless; es lo que hacia el diseno original).

El latch de PC4 que muestra el firmware (nunca hace `cbi` de PC4) se autode limpia solo en
este circuito: al apagarse la fuente se pierde el USB 5V del controller => AVR apaga =>
boot init libera PC4. Por eso la bobina **debe** alimentarse del 5V del USB del host, no de
5VSB: es el mecanismo de re-encendido.

## Fase 1 - Identificar hilos (multimetro, sin soldar)

Del **conector del controller** (pines ya rotulados en el silkscreen, ver
`hardware-mods.md` -> "Conector del controller"): solo falta caracterizarlos, no adivinarlos:

1. **GND**: pin `GND` del conector USB-A del controller.
2. **PWR SW** (= PC4): con el controller en USB de una maquina de prueba, `fan_controller_cli
   -p` y medir entre los 2 pines del header rotulado y contra GND: determinar si es contacto
   seco (cierra a GND), push-pull (5 V persistente) o sink activo-bajo. Confirmar que al
   desenchufar el USB del controller queda libre/auto-liberado.
3. **RST SW** (= PC3): con `-x`, pulso de ~0.3 s en el header rotulado (misma
   caracterizacion; si el multimetro no lo alcanza, LED+R en serie).
4. **USB 5V**: pin `5V` del conector USB-A (alimentacion de la bobina del relay).

Del **JATX (lado backplane)**: cable de 6 hilos ya identificado:
`5VSB - SVSB - PSON - PSON - GND - GND` (hoy UNO de los PSON esta puenteado a GND).

5. Confirmar con multimetro cuales pines fisicos corresponden al PSON puenteado (el del
   puente actual) y dejar el **segundo PSON libre** como punto de corte del relay: el
   contacto NC del relay ira entre ese PSON y GND, y el puente actual se convierte en el
   override manual de mantenimiento.
6. Verificar continuidad de `5VSB`/`SVSB` hacia el backplane: informativo (el diseno no lo
   usa, pero define alternativas futuras).

## Fase 2 - Circuito

Opcion simple (recomendada): **modulo relay 1 canal** (optoaislado, trigger alto o bajo,
cualquier servo-module de 5 V sirve) + logica:

- `VCC` del modulo <- USB 5V del arnes del controller (con el host prendido).
- `IN` <- PC4 (con R 1k en serie; 10k pull-down de IN a GND si el modulo es trigger-alto
  para que float = sin disparo).
- Contacto **NC** del relay en paralelo con el punto del puente PS_ON-GND actual.
- Dejar un **switch/toggle manual** en serie con el puente como override de mantenimiento
  (ON fuerza = fuente prendida sin importar el relay).

Si el modulo es trigger-BAJO (comun en modulos chinos), invertir la logica con un NPN extra
o usar un PNP en el alto: PC4 low => IN=GND => energizado => NC **abierto** => fuente OFF.
MAL: ahi la normalidad apagara la fuente. Con trigger-bajo usar contacto **NO** invertido...
Regla simple y a prueba de olvido: **con el host prendido y PC4 low, el contacto debe estar
CERRANDO PS_ON-GND**. Medir con multimetro antes de conectar la fuente al bucle.

Alternativa discreta (sin modulo): relay 5 V (bobina <= 5V USB), NPN 2N2222 con base a PC4
via 1k + 10k pull-down, diodo de rueda libre 1N4148 en la bobina, contacto NC sobre
PS_ON-GND.

## Fase 3 - Pruebas en banco (fuente sin Xeon conectado, o con EPS desconectado)

1. Controller USB a notebook => `-p`: el relay debe atraer (click), fuente OFF, notebook
   pierde el USB, relay suelta, fuente ON. Ciclo completo observable.
2. Medir duracion del off: es el tiempo entre latch de PC4 y perdida de 5V (debe ser
   instantaneo; el off dura lo que tarda la fuente en morir + el AVR en apagarse = ~2-5 s
   de off real + boot de la placa).
3. **Prueba critica de auto-arranque**: con la ZX-DU99D4 conectada (pico + EPS), cortar la
   fuente grande por `-p` y verificar que la placa **arranca sola** cuando vuelve el 12 V.
   - Si arranca: fin, todo firmware.
   - Si NO arranca (queda en S5 porque su PS_ON a la pico sigue desasertado): probar BIOS
     `Restore on AC / Power Loss = Power On` (muchas AMI chicas lo tienen y la pico hace
     desaparecer la 5VSB falsa al irse el 12 V).
   - Si aun asi no: Plan B queda como "apagado remoto" y el re-encendido lo resuelve el
     Plan C (PDU IP) => la combinacion B+C cubre todo igual.
4. Integracion: volver a `watchdog.enabled: true` con los valores de prod y probar
   desalimentando a proposito (parar el daemon o tumbar SSH) y observar escalada completa.

## Notas y riesgos

- PC3/PC4 son push-pull 5 V: hacia el F_PANEL de la placa (RESET_SW del Plan A) SIEMPRE por
  transistor o R serie, nunca directo (pull-up interno de 3.3 V de la placa).
- El relay ve 12 V de la fuente "de lado", pero solo conmuta PS_ON-GND (senal): sin riesgos
  de potencia.
- Si el controller queda alimentado por una fuente que no muere con el rig (powerbank, otro
  host), el latch de PC4 **no se autode limpia** y el rig queda apagado permanentemente.
  Por eso: bobina solo desde el USB del propio host.
- Firmware revisado: no existe re-pulso de PC4; todo el re-encendido depende de la perdida
  de power del AVR, tal como esta disenado el circuito de arriba.

## Pendientes

- [ ] Medir PC3/PC4/5V/GND en el arnes del controller (Fase 1 items 1-4)
- [ ] Confirmar PS_ON/5VSB en JATX (items 5-6)
- [ ] Probar `-p` en banco con el relay (Fase 3.1-3.2)
- [ ] Verificar auto-arranque de la placa (item 3) y definir si hace falta BIOS/PDU
- [ ] Registrar el pinout final del arnes aca mismo y en `hardware-mods.md`
