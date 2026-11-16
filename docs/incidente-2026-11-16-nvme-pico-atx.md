# Incidente 2026-11-15/16: caidas del NVMe raiz, watchdog y causa (pico ATX)

Registro completo de las pruebas hechas mientras se instalaba DeepSeek-V4.1-Flash con Project Maya
(`docs/maya-deepseek.md`). Resumen:

- El NVMe raiz (Samsung 980 PRO 2 TB, root port `00:01.0`) se cayo del bus **5 veces de forma fatal** (y tuvo varios
  SDES recuperados) con AER Fatal `SDES` (Surprise Down). El SSD esta sano (SMART limpio).
- **Causa (evidencia fuerte): la pico ATX de 120 W que alimenta el conector de 24 pines estaba gastada.**
  Su rail de 3,3 V (el unico que alimenta un M.2) bajaba a ~3,0 V con el NVMe trabajando; minimo de
  especificacion 3,135 V. Con una pico nueva el rail queda >= 3,15 V y el disco aguanta escritura
  sostenida a 2 GB/s.
- El watchdog del firmware Octofan tardo ~3 h en resetear un host colgado: se agrego el **watchdog del
  chipset (iTCO)** como segunda via de reset (commit `0720cb2`), probado.
- El cable de reset del Octofan quedo **desconectado**: reseteaba la placa en POST/BIOS durante el
  mantenimiento.

## Hardware involucrado

- Placa ZX-DU99D4 (X99, chipset Wellsburg), 2x E5-2680 v4, 125 GB RAM, 4x RTX 3090 en risers con
  alimentacion propia por 6 pines.
- Alimentacion: fuente del Octominer siempre encendida (EPS de los CPU, 12 V de risers y fans) y una
  **pico ATX de 120 W** desde su 12 V para el conector de 24 pines: RAM, chipset, USB, **3,3 V de los slots
  PCIe y del M.2**. Ver `hardware-mods.md`.
- Sensor de voltajes de la placa: Nuvoton **NCT6779D** (`modprobe nct6775`; persistido en
  `/etc/modules-load.d/nct6775.conf`). `in3` = 3VCC (3,3 V principal), `in2` = AVCC, `in7` = 3VSB.
  En Prometheus: `node_hwmon_in_volts{chip="platform_nct6775_2592",sensor="in3"}`.

## Cronologia de las caidas

Capturadas transmitiendo `dmesg -wT` a otra maquina (el journal local se pierde con el disco).

| # | Hora | Carga en el NVMe | Resultado |
|---|---|---|---|
| 1 | 11-16 00:22:51 | `hf download` (xet) ~90 MB/s de escritura + build de imagen Docker | SDES, XFS apagado. PID 1 murio -> kernel panic -> **kdump reinicio** (`/var/crash/127.0.0.1-2026-11-16-00:23:14`) |
| 2 | 00:26:53 | curl limitado a 45 MB/s + Strata cargando, 2 min despues del arranque | SDES, "device recovery failed". Host colgado en RAM **~3 h**: el Octofan reseteo recien a las 03:29 |
| 3 | 09:36:44 -> 09:37:54 | aria2 x16 ~94 MB/s de escritura sostenida durante ~27 min | Dos SDES recuperados (aviso previo) y el tercero fatal. **El iTCO reseteo en ~3,5 min** |
| - | 09:44-09:45 | Solo la carga de Strata (lectura), sin descargas | Varios SDES recuperados |
| 4 | 12:16:11 | Lectura liviana (pack del drafter, ~8 GB), 2 min despues del arranque, Gen3 | SDES fatal, el iTCO reseteo |
| 5 | 12:23:09 | Enlace forzado a **Gen2** (5 GT/s); escritura del pack del drafter | SDES fatal: bajar la velocidad no lo arregla |
| 6 | 13:55:41 | Lectura de prueba de 48 GB a Gen2, midiendo 3,3 V | SDES recuperado, **con 3,3 V en 3,008 V** |

Las caidas anteriores del mismo tipo (`gpu-link-drop`, NVMe del 2026-11-10, I/O colgado del 2026-10-20)
encajan con la misma causa: los slots PCIe de las GPU tambien toman 3,3 V de la pico.

## Diagnostico

### El SSD esta sano

Conectado a otra PC con un adaptador USB RTL9210 (`smartctl -d sntrealtek`): firmware `5B2QGXA7` (sin el
bug de degradacion de los 980 PRO), 0 errores de medio e integridad, 3 % de desgaste, 100 % de spare, 34 C,
7911 h, 18,7 TB escritos.

### No es la velocidad del enlace

`setpci -s 00:01.0 CAP_EXP+30.w=0002:000f` (target Gen2) + `CAP_EXP+10.w=0020:0020` (reentrenar): el
enlace pasa a 5 GT/s sin cortes. A Gen2 leyo 47 GB a 1,7 GB/s sin errores, pero se cayo igual al escribir
(caida 5) y tuvo un SDES leyendo (caida 6). El servicio que fijaba Gen2 se desactivo.

### Es el rail de 3,3 V

Muestreo de `in3` cada 0,2 s (`/sys/class/hwmon/hwmonN/in3_input`):

| Prueba | Pico ATX vieja | Pico ATX nueva |
|---|---|---|
| Reposo (GPU sin carga) | 3,200 V | 3,280-3,296 V |
| Lectura 48 GB (`dd iflag=direct`) | prom. 3,028 / **min 3,008 V**, SDES, 1,5 GB/s (Gen2) | prom. 3,219 / min 3,184 V, sin errores, **3,2 GB/s (Gen3)** |
| Escritura 40 GB (`dd oflag=direct`) | (se caia en minutos aun a 45-90 MB/s) | prom. 3,185 / **min 3,152 V**, sin errores, 2,0 GB/s |
| Descarga real de 114 GB (aria2 ~86 MB/s) + Maya sirviendo | - | min 3,168 V, sin errores |

Minimo de especificacion ATX/M.2: 3,3 V - 5 % = **3,135 V**. La vieja quedaba ~130 mV por debajo leyendo;
una caida de ~190 mV con ~1,5 A extra (~0,13 ohm efectivos) no es la de un regulador sano. La nueva entra
en especificacion pero con poco margen (17 mV) en escritura a fondo.

**Pendiente: reemplazar la pico por una fuente con mas corriente en 3,3 V.** Candidata evaluada:
AcBel PCA023 (300 W, 3,3 V 19 A, 5 V 15 A, 12V1 8 A). Sirve porque los risers toman 12 V por sus 6 pines
(el 24 pines solo carga ~50-70 W). Requisitos: 24 pines ATX estandar (o un buen adaptador), mismo enchufe
Tuya que la fuente del Octominer y BIOS `Restore on AC Power Loss = Power On`.

## Watchdog

### El firmware Octofan no reseteo un host colgado durante ~3 h

En la caida 2 el host quedo vivo en RAM (ping si, ssh no, todo `exec` con EIO). El daemon no podia
alimentar (EIO), el firmware estaba armado (`mode 2`) y aun asi el Reset Counter paso de 21 a 22 recien a
las 03:29. No se encontro la causa (esta en el firmware). El reinicio de las 00:24 no fue el watchdog
(kdump, el contador no cambio).

### Segundo watchdog: iTCO del chipset (commit `0720cb2`)

El controller abre `/dev/watchdog` (`iTCO_wdt`, Wellsburg TCO v2) con `watchdog.host_device` y
`host_timeout_seconds: 180`, y lo alimenta con la misma politica que al firmware. Detalles en
`operations.md`. Probado:

- 08:48: con el Octofan alimentado, abrir y cerrar `/dev/watchdog` sin `V` -> reset a los **177 s**;
  Reset Counter del Octofan sin cambios (lo hizo el chipset). Vuelta a ssh ~50 s despues.
- Caidas 3, 4 y 5: el iTCO reseteo solo en ~3,5 min cada vez. XFS se recupero limpio en cada una
  (salvo una vez, ver abajo).

### El Octofan reseteaba la placa en POST/BIOS

El AVR del Octofan tiene alimentacion aunque el host este apagado. Armado y sin nadie que lo alimente
(host apagado, sin disco o en la BIOS), pulsaba RESET en medio del arranque: Reset Counter 22 -> 23
(10:00-12:14, con el disco fuera) y 23 -> 24 (12:32-13:00, al mover el NVMe). Sumado a no ver video, el
arranque parecia roto. El usuario **desconecto el cable RST SW -> RESET_SW**; el reset automatico queda solo
en el iTCO, que Linux arma recien al arrancar el controller y nunca dispara en POST/BIOS
(`watchdog-power-cycle.md`).

Riesgo conocido (no implementado): una falla permanente que el daemon detecte (p. ej. una GPU muerta con
`gpus_expected: 4`) haria un loop de reinicios. Propuesta: freno anti-loop que pase a solo-keepalive tras
N resets por watchdog en una hora.

## Recuperacion del filesystem (no booteaba)

Tras la caida 3 el XFS raiz no montaba: `Failed to recover intents` / `log mount finish failed` (el
arranque quedaba en modo emergencia). Con el disco por USB en otra PC:

1. LVM en solo lectura: `vgchange -ay --devices /dev/sdc3 --config 'activation { read_only_volume_list =
   [ "octoserver-2tb" ] }'` (RHEL 10 filtra PVs ajenos con `system.devices`).
2. `xfs_repair -n` y montaje `ro,norecovery,nouuid` para inspeccionar.
3. Respaldo de metadatos: `xfs_metadump -g -o` (1,7 GB, guardado fuera del server).
4. `xfs_repair -L` (descarta el journal roto) y una segunda pasada normal; `xfs_repair -n` final limpio.
5. Perdidas: `/var/lib/docker/{tmp,runtimes}` y dos `work/work` de snapshots de containerd (se recrean
   solos), un `resolv.conf` huerfano a `lost+found`. `rpm -Va` sin binarios ni librerias alterados.
6. Los shards del modelo escritos antes de las caidas se verificaron por sha256: todos OK.

## Video para la BIOS

Solo la **GPU 0** (bus `02:00.0`, `boot_vga=1`) da imagen en POST/BIOS/GRUB. Con el monitor en otra placa
no se ve nada hasta que carga el driver NVIDIA. Para ubicarla fisicamente (risers): ventiladores al 100 %
por NVML durante 90 s y vuelta a automatico (`nvmlDeviceSetFanSpeed_v2` / `nvmlDeviceSetDefaultFanSpeed_v2`,
`nvidia-ml-py`); en reposo las otras tres tienen los fans parados. El conector con monitor se ve en
`/sys/class/drm/card*-*/status`.

## Descarga del modelo

- `hf download` con xet: hasta 11 + 18 GB de RSS con dos procesos, no retoma parciales; sin xet el CLI se
  niega con archivos grandes. curl de una conexion: ~27 MB/s.
- **aria2c `-x 16 -s 16`**: ~90 MB/s. Error propio: un `curl` viejo y aria2 escribieron el mismo `.part`
  a la vez y corrompieron dos shards (el sha256 lo detecto; se bajaron de nuevo).
- Mientras el server estaba caido se bajo en otra PC con rangos paralelos de curl escritos con `pwrite`
  en su offset (evita concatenar: en un HDD concatenar iba a ~50 MB/s) y se copio por USB al disco del
  server.
- Todo verificado por sha256 contra `tools/ds4/download_gguf.json` de Maya v1.1.65.

## Resultado

DeepSeek-V4.1-Flash abliterado **Mix-128G** en Maya queda como servicio diario (benchmarks en
`maya-deepseek.md`: ~1000 tok/s de prefill, 44-50 tok/s de decode, 1M de contexto, vision, tool use en
OpenCode). Mix-256G queda en disco (~4x mas lento: no entra en VRAM + RAM).
