"""Exact current images with batch-local decoding, rather than retained JSON trees."""
from collections.abc import MutableMapping
import json


class CurrentBookImages(MutableMapping):
    def __init__(self):
        self.encoded = {}
        self.encoded_bytes = 0

    def __getitem__(self, key):
        return json.loads(self.encoded[key])

    def __setitem__(self, key, value):
        image = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
        self.encoded_bytes += len(image) - len(self.encoded.get(key, b''))
        self.encoded[key] = image

    def __delitem__(self, key):
        self.encoded_bytes -= len(self.encoded.pop(key))

    def __iter__(self):
        return iter(self.encoded)

    def __len__(self):
        return len(self.encoded)

    def __contains__(self, key):
        return key in self.encoded

    def clear(self):
        # MutableMapping.clear would decode every discarded image through popitem.
        self.encoded.clear()
        self.encoded_bytes=0

    def copy(self):
        result = type(self)()
        result.encoded = self.encoded.copy()
        result.encoded_bytes = self.encoded_bytes
        return result

    def retain_from(self, other, keys):
        """Keep unchanged images through catalog replacement without decoding."""
        for key in keys:
            image = other.encoded[key]
            self.encoded_bytes += len(image) - len(self.encoded.get(key, b''))
            self.encoded[key] = image
