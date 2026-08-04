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
