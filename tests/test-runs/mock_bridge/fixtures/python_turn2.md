Project: python-lru-cache

File: src/lru_cache.py
```python
from collections import OrderedDict
from typing import Any, Dict, List


class LRUCache:
    """Least Recently Used (LRU) Cache implemented using collections.OrderedDict."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Capacity must be >= 1")
        self.capacity: int = capacity
        self.hits: int = 0
        self.misses: int = 0
        self._cache: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value if present and mark key as most recently used, else return default."""
        if key not in self._cache:
            self.misses += 1
            return default
        self.hits += 1
        self._cache.move_to_end(key, last=True)
        return self._cache[key]

    def put(self, key: str, value: Any) -> None:
        """Insert or update key as most recently used, evicting the LRU item if over capacity."""
        if key in self._cache:
            self._cache.move_to_end(key, last=True)
        self._cache[key] = value
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        """Remove the key and return True if it existed, else False."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def size(self) -> int:
        """Return the current number of items in the cache."""
        return len(self._cache)

    def keys(self) -> List[str]:
        """Return keys ordered from least to most recently used."""
        return list(self._cache.keys())

    def stats(self) -> Dict[str, int]:
        """Return cache statistics including hits, misses, current size, and capacity."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": self.size(),
            "capacity": self.capacity,
        }
```

File: tests/test_lru_cache.py
```python
import os
import sys
import unittest

# Ensure imports work regardless of the current working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from src.lru_cache import LRUCache
except ImportError:
    from lru_cache import LRUCache


class TestLRUCache(unittest.TestCase):
    def test_invalid_capacity_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LRUCache(0)
        self.assertEqual(str(ctx.exception), "Capacity must be >= 1")

        with self.assertRaises(ValueError):
            LRUCache(-5)

    def test_lru_eviction_order_and_refresh_on_get(self) -> None:
        cache = LRUCache(capacity=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)

        self.assertEqual(cache.keys(), ["a", "b", "c"])

        # Access "a" to refresh it as most recently used
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.keys(), ["b", "c", "a"])

        # Insert "d", exceeding capacity and evicting "b" (least recently used)
        cache.put("d", 4)
        self.assertEqual(cache.size(), 3)
        self.assertEqual(cache.keys(), ["c", "a", "d"])
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("c"), 3)
        self.assertEqual(cache.get("d"), 4)

    def test_stats_tracks_hits_and_misses_accurately(self) -> None:
        cache = LRUCache(capacity=2)
        self.assertEqual(
            cache.stats(),
            {"hits": 0, "misses": 0, "size": 0, "capacity": 2},
        )

        cache.put("x", 10)
        cache.put("y", 20)

        # Two hits
        self.assertEqual(cache.get("x"), 10)
        self.assertEqual(cache.get("y"), 20)

        # Three misses (including one with a custom default)
        self.assertIsNone(cache.get("z"))
        self.assertEqual(cache.get("missing", default=-1), -1)
        self.assertIsNone(cache.get("unknown"))

        self.assertEqual(cache.hits, 2)
        self.assertEqual(cache.misses, 3)
        self.assertEqual(
            cache.stats(),
            {"hits": 2, "misses": 3, "size": 2, "capacity": 2},
        )

    def test_delete_removes_keys_properly(self) -> None:
        cache = LRUCache(capacity=3)
        cache.put("k1", "v1")
        cache.put("k2", "v2")

        # Delete existing key
        self.assertTrue(cache.delete("k1"))
        self.assertEqual(cache.size(), 1)
        self.assertEqual(cache.keys(), ["k2"])
        self.assertIsNone(cache.get("k1"))

        # Delete non-existent key
        self.assertFalse(cache.delete("k1"))
        self.assertFalse(cache.delete("non_existent"))
        self.assertEqual(cache.size(), 1)


if __name__ == "__main__":
    unittest.main()
```

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

