"""CPU budgets shared by OCR workers and the local inference runtime."""
import math
import os
from pathlib import Path


def available_cpus():
    """Respect affinity and Linux container quotas; also works on macOS."""
    count = os.cpu_count() or 1
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            count = min(count, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return max(1, count)


def cpu_setting(name):
    """An optional positive override can reduce, never exceed, the CPU budget."""
    count = available_cpus()
    raw = os.environ.get(name, '').strip()
    if not raw:
        return count
    try:
        return max(1, min(count, int(raw)))
    except ValueError:
        return count
