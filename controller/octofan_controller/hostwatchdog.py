"""Linux hardware watchdog (/dev/watchdog, e.g. the chipset iTCO) fed by the daemon.

Second, independent reset path next to the Octofan firmware watchdog: it does not
depend on the USB AVR, its firmware or the RESET wire. On 2026-11-16 the root NVMe
dropped off the bus, the host stayed alive in RAM with every exec failing, and the
firmware (armed, unfed) took ~3 h to reset the board. The chipset timer resets the
host on its own once the daemon stops feeding it.

Feeding is a write on an fd opened at startup, so it keeps working with a dead disk.
A clean shutdown writes the magic 'V' (nowayout=0) so recreating the controller does
not reset the host; a crash leaves the timer running and the next daemon picks it up.
"""

from __future__ import annotations

import fcntl
import os
import struct

# <linux/watchdog.h>: _IOWR('W', 6, int)
WDIOC_SETTIMEOUT = 0xC0045706


class HostWatchdog:
    def __init__(self, device: str, timeout_seconds: int) -> None:
        self.device = device
        self.requested_timeout = timeout_seconds
        self.timeout: int | None = None
        self._fd: int | None = None

    @property
    def armed(self) -> bool:
        return self._fd is not None

    def open(self) -> None:
        """Open (which starts the timer) and set the timeout. Raises OSError."""
        if self._fd is not None:
            return
        fd = os.open(self.device, os.O_WRONLY)
        self._fd = fd
        try:
            raw = fcntl.ioctl(fd, WDIOC_SETTIMEOUT, struct.pack("i", self.requested_timeout))
            self.timeout = struct.unpack("i", raw)[0]
        except OSError:
            # Never run on the driver default (iTCO: 30 s, the feed interval): a
            # timeout that short would reset a healthy host. Stop it and fail.
            self.disarm()
            raise

    def feed(self) -> None:
        if self._fd is None:
            raise OSError(f"{self.device} is not open")
        os.write(self._fd, b"\0")

    def disarm(self) -> None:
        """Magic close: stop the timer. Only for intentional shutdowns."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            os.write(fd, b"V")
        finally:
            os.close(fd)
