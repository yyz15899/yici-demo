"""公开接口限流：每 IP 每分钟滑动窗口计数。

内存实现，适用于单进程部署；多进程/多实例需换共享存储（如 Redis）。
只限制 analyze，healthz 不受影响。
"""

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """每 IP 每分钟固定窗口计数，内存实现，单进程部署够用。"""

    def __init__(self, per_minute: int):
        self._per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """记录一次访问并判断是否放行。per_minute<=0 表示不限流。"""
        if self._per_minute <= 0:
            return True
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self._per_minute:
            return False
        window.append(now)
        return True