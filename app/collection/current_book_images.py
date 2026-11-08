"""Exact current images with batch-local decoding, rather than retained JSON trees."""
from collections.abc import MutableMapping
import json
import zlib


def encode_container(value):
    """Pack an already validated JSON value for temporary process-local ownership."""
    raw = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
    if len(raw) >= 1024:
        packed = zlib.compress(raw, level=1)
        if len(packed) + 1 < len(raw):
            return b'\0' + packed
    return raw


def decode_container(image):
    if image.startswith(b'\1'):
        size=int.from_bytes(image[1:5],'big')
        overlay=json.loads(image[5:5+size])
        value=decode_container(image[5+size:])
        value['raw']['exchange_at']=overlay['exchange_at']
        if overlay['confirmation'] is not None:value['book_confirmation']=overlay['confirmation']
        return value
    if image.startswith(b'\0'):
        image = zlib.decompress(image[1:])
    return json.loads(image)


class CurrentBookImages(MutableMapping):
    def __init__(self):
        self.encoded = {}
        self.encoded_bytes = 0

    def __getitem__(self, key):
        return decode_container(self.encoded[key])

    def __setitem__(self, key, value):
        image = encode_container(value)
        self.set_encoded(key,image)

    def set_prepared(self,key,image,*,exchange_at,confirmation):
        """Child-packed complete image plus parent-owned clock/confirmation.

        Reconstruction owns the large immutable book. Lifecycle admission can
        preserve its prior exchange clock, and confirmation belongs to the live
        socket owner. Neither requires recompressing every ladder on that loop.
        """
        overlay=json.dumps(dict(exchange_at=exchange_at,confirmation=confirmation),separators=(',',':')).encode()
        self.set_encoded(key,b'\1'+len(overlay).to_bytes(4,'big')+overlay+image)

    def set_encoded(self,key,image):
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

    def take(self, keys):
        """Transfer immutable images without decoding on the socket event loop."""
        result = type(self)()
        for key in keys:
            image = self.encoded.pop(key)
            result.encoded[key] = image
            result.encoded_bytes += len(image)
            self.encoded_bytes -= len(image)
        return result

    def retain_from(self, other, keys):
        """Keep unchanged images through catalog replacement without decoding."""
        for key in keys:
            image = other.encoded[key]
            self.encoded_bytes += len(image) - len(self.encoded.get(key, b''))
            self.encoded[key] = image
