"""Borrow image readers and export only rows requested by the bounded scheduler."""
from collections.abc import Sequence
from contextlib import closing, contextmanager
import operator


@contextmanager
def read_only_rgba(image):
    """Borrow decoded RGBA; close only the conversion this reader owns."""
    rgba = image if image.mode == 'RGBA' else image.convert('RGBA')
    try:
        yield rgba
    finally:
        if rgba is not image:
            rgba.close()


class RgbaRowTasks(Sequence):
    """Lazy, repeatable row tasks with ordinary pickleable byte payloads.

    ResourceAllocation.parallel_map bounds outstanding submissions. Holding this
    sequence does not retain a full raw export or prebuild every task's bytes;
    each requested crop is closed before its independent payload is submitted.
    The producer alone reads the borrowed image, and workers receive only bytes.
    """
    def __init__(self, image, ranges, suffix, *, cancelled=lambda: False):
        if image.mode != 'RGBA':
            raise ValueError('Row tasks require normalized RGBA pixels.')
        self.image = image
        self.ranges = tuple(ranges)
        self.suffix = tuple(suffix)
        self.cancelled = cancelled

    def __len__(self):
        return len(self.ranges)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        index = operator.index(index)
        y0, y1 = self.ranges[index]
        if self.cancelled():
            raise InterruptedError('Row export cancelled.')
        with closing(self.image.crop((0, y0, self.image.width, y1))) as rows:
            if self.cancelled():
                raise InterruptedError('Row export cancelled.')
            payload = rows.tobytes()
        if self.cancelled():
            raise InterruptedError('Row export cancelled.')
        return (y0, self.image.width, payload, *self.suffix)
