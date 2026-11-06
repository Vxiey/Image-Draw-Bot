"""Atomic output for the optional, user-started screen recording tool."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


def save_gif_atomic(destination, frames, durations):
    """Publish a complete GIF while preserving an existing file on failure."""
    destination = Path(destination)
    if not frames or len(frames) != len(durations):
        raise ValueError('A recording needs one duration per frame.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w+b', prefix=f'.{destination.name}.', suffix='.tmp',
            dir=destination.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            frames[0].save(stream, format='GIF', save_all=True,
                           append_images=frames[1:], duration=durations,
                           loop=0, optimize=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Cleanup cannot mask the encoding or publication error.
