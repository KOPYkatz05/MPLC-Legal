"""Loading and cache decisions for Missionary Detail."""

import time

from .state import MissionaryDetailState


class MissionaryDetailCoordinator:
    """Coordinate request identity and snapshot caching without widget access."""

    def __init__(self, state=None, clock=None):
        self.state = state or MissionaryDetailState()
        self._clock = clock or time.monotonic

    def begin(self, missionary_id):
        self.state.begin_request(missionary_id)

    def accepts(self, missionary_id):
        return self.state.accepts(missionary_id)

    def cached(self, missionary_id):
        return self.state.snapshot_cache.get(missionary_id)

    def cache_is_fresh(self, missionary_id):
        cached = self.cached(missionary_id)
        return bool(
            cached is not None
            and self._clock() - cached["loaded_at"]
            < self.state.cache_ttl_seconds
        )

    def store(self, missionary_id, snapshot):
        self.state.snapshot_cache[missionary_id] = {
            "snapshot": snapshot,
            "loaded_at": self._clock(),
        }

    def invalidate(self, missionary_id):
        self.state.snapshot_cache.pop(missionary_id, None)
