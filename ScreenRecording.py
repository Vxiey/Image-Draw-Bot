"""Atomic output for the optional, user-started screen recording tool."""
from __future__ import annotations

import os
import math
from numbers import Real
from pathlib import Path
import tempfile


def gif_durations(durations):
    """Quantize cumulative recording time to GIF's 10 ms clock.

    Rounding each frame down independently makes a recording run faster. Keep
    each cumulative frame boundary within half a GIF tick instead. The screen
    recorder supplies at least 20 ms per frame, including a final Stop frame.
    """
    result=[];elapsed=0.0;published_ticks=0
    for duration in durations:
        if isinstance(duration,bool) or not isinstance(duration,Real):
            raise ValueError('Recording frame durations must be finite milliseconds.')
        try:value=float(duration)
        except (OverflowError,ValueError) as error:
            raise ValueError('Recording frame duration is out of range.') from error
        if not math.isfinite(value) or not 20<=value<=655350:
            raise ValueError('Recording frame durations must be between 20 and 655350 ms.')
        elapsed+=value
        ticks=math.floor(elapsed/10+.5)
        result.append((ticks-published_ticks)*10)
        published_ticks=ticks
    return result


def append_recorded_frame(frames, durations, frame, duration):
    """Retain a new visible frame, or extend an identical adjacent frame.

    Return whether ownership moved into ``frames``. The capture caller closes
    an unretained frame. Compare palette colours as well as pixel indexes: two
    independently quantized captures can use the same indexes for other colours.
    """
    if frames:
        previous=frames[-1]
        if (frame.mode==previous.mode and frame.size==previous.size
                and frame.info.get('transparency')==previous.info.get('transparency')
                and frame.getpalette('RGBA')==previous.getpalette('RGBA')
                and frame.tobytes()==previous.tobytes()):
            durations[-1]+=duration
            return False
    frames.append(frame)
    durations.append(duration)
    return True


def save_gif_atomic(destination, frames, durations):
    """Publish a complete GIF while preserving an existing file on failure."""
    destination = Path(destination)
    if not frames or len(frames) != len(durations):
        raise ValueError('A recording needs one duration per frame.')
    durations=gif_durations(durations)
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
