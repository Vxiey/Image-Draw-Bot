"""Select verification pixels from delivered geometry with bounded scratch space."""
from itertools import pairwise


def representative_segment(subpaths, *, cancelled=lambda: False):
    """Return the first longest nonzero segment, or the first isolated dot.

    Separate clipped subpaths must never be joined to create a verification
    segment through pixels where no ink was sent. Input geometry is borrowed.
    """
    anchor = None
    best = None
    best_squared = -1
    visited = 0
    if cancelled():raise InterruptedError('Stroke verification sampling cancelled.')
    for path_index, path in enumerate(subpaths):
        if path_index % 1024 == 0 and cancelled():
            raise InterruptedError('Stroke verification sampling cancelled.')
        if not path:continue
        if anchor is None:anchor = path[0]
        for start, end in pairwise(path):
            if visited % 1024 == 0 and cancelled():
                raise InterruptedError('Stroke verification sampling cancelled.')
            visited += 1
            if start == end:continue
            squared = (end[0]-start[0])**2 + (end[1]-start[1])**2
            if squared > best_squared:
                best_squared = squared
                best = (start, end)
    if cancelled():raise InterruptedError('Stroke verification sampling cancelled.')
    if anchor is None:raise ValueError('A stroke probe needs delivered geometry.')
    return best if best is not None else (anchor, anchor)
