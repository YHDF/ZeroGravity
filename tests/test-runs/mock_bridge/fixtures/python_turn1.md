Project: python-lru-cache

File: src/lru_cache.py
```python
from collections import OrderedDict
from typing import Any, List


class LRUCache:
    """Least Recently Used (LRU) Cache implemented using collections.OrderedDict."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Capacity must be >= 1")
        self.capacity: int = capacity
        self._cache: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value if present and mark key as most recently used, else return default."""
        if key not in self._cache:
            return default
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
```

File: src/cli.py
```python
import os
import sys

# Ensure imports work regardless of whether executed from the project root or src/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from src.lru_cache import LRUCache
except ImportError:
    from lru_cache import LRUCache


def main() -> None:
    cache = LRUCache(capacity=3)

    # Insert initial items
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)

    # Access "a" so it becomes the most recently used item
    _ = cache.get("a")

    # Insert "d", which exceeds capacity and evicts the least recently used item ("b")
    cache.put("d", 4)

    # Print remaining keys (ordered from least to most recently used) and their values
    remaining_keys = cache.keys()
    print(f"Remaining keys (LRU -> MRU): {remaining_keys}")
    for key in remaining_keys:
        print(f"{key}: {cache.get(key)}")


if __name__ == "__main__":
    main()
```

```bash
python3 src/cli.py
```

