#!/usr/bin/env python3
"""Thread-safe LRU cache implementations."""

import threading
from collections import OrderedDict


class LRUCache:
    """Thread-safe LRU cache with max size."""
    
    def __init__(self, max_size: int = 1000):
        self._cache = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
    
    def get(self, key):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None
    
    def set(self, key, value):
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
    
    def has(self, key) -> bool:
        with self._lock:
            return key in self._cache
    
    def clear(self):
        with self._lock:
            self._cache.clear()
    
    def __len__(self):
        with self._lock:
            return len(self._cache)

    # ── dict 协议 ─────────────────────────────────────────────
    # 让 `k in cache` / `cache[k] = v` / `cache.pop(k)` 三种写法成立，目的是
    # **把一个裸 dict 缓存整体换成 LRUCache 时不必改任何调用点** —— 包括已有的
    # 回归测试（`test_analysis_info_nonblocking.py` 直接操作
    # `pubmed._EUROPE_PMC_CACHE`，用的就是这三种写法）。
    # 少了这层，迁移就必然要顺手改测试，而「改测试」正是把回归测试改松
    # 最常见的入口：看起来只是换了个赋值语法，实际是重新审一遍断言。
    # 生产代码仍统一走 .get()/.set()（与 search/scanner/routes 一致）。

    def __contains__(self, key) -> bool:
        return self.has(key)

    def __setitem__(self, key, value) -> None:
        self.set(key, value)

    def pop(self, key, default=None):
        """单键失效。不存在时返回 default。"""
        with self._lock:
            if key in self._cache:
                return self._cache.pop(key)
            return default
