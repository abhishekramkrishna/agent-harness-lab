"""A small least-recently-used cache."""

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.data: OrderedDict = OrderedDict()

    def get(self, key, default=None):
        if key not in self.data:
            return default
        return self.data[key]

    def put(self, key, value) -> None:
        self.data[key] = value
        if len(self.data) > self.capacity:
            self.data.popitem(last=False)
