"""
Process resource sampler for the live dashboard (no psutil dependency).

Uses stdlib `resource` + `time.process_time` so macOS/Linux both work
under the pinned-deps policy.
"""

from __future__ import annotations

import os
import platform
import resource
import time
from dataclasses import dataclass


@dataclass(slots=True)
class SystemSample:
    ram_mb: float
    cpu_percent: float


class SystemMetricsSampler:
    def __init__(self) -> None:
        self._prev_process: float | None = None
        self._prev_wall: float | None = None

    def sample(self) -> SystemSample:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # Linux reports ru_maxrss in KiB; macOS in bytes.
        rss = float(usage.ru_maxrss)
        if platform.system() == "Darwin":
            ram_mb = rss / (1024 * 1024)
        else:
            ram_mb = rss / 1024

        now_process = time.process_time()
        now_wall = time.perf_counter()
        cpu = 0.0
        if self._prev_process is not None and self._prev_wall is not None:
            d_proc = now_process - self._prev_process
            d_wall = now_wall - self._prev_wall
            if d_wall > 0:
                # Cap at 100% * cpu_count for multi-thread noise.
                cpus = max(1, os.cpu_count() or 1)
                cpu = min(100.0 * cpus, (d_proc / d_wall) * 100.0)

        self._prev_process = now_process
        self._prev_wall = now_wall

        return SystemSample(ram_mb=ram_mb, cpu_percent=cpu)
