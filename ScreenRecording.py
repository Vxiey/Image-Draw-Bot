"""Atomic output for the optional, user-started screen recording tool."""
from __future__ import annotations

import math
from contextlib import closing
from numbers import Real
from pathlib import Path

from RuntimePaths import atomic_binary_writer


def _same_recorded_pixels(first, second):
    """Compare exact storage without exporting two complete large captures.

    Full-width strips preserve packed row padding, including mode ``1``. At
    most 65536 pixels (or one exceptionally wide row) are exported per strip;
    the recorder itself caps captures at 800 pixels wide. Small frames retain
    Pillow's direct byte comparison and no caller-owned image is closed.
    """
    width, height = first.size
    if width * height <= 65536:
        return first.tobytes() == second.tobytes()
    rows = max(1, 65536 // width)
    for top in range(0, height, rows):
        box = (0, top, width, min(height, top + rows))
        with closing(first.crop(box)) as left, closing(second.crop(box)) as right:
            if left.tobytes() != right.tobytes():
                return False
    return True


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
                and _same_recorded_pixels(frame,previous)):
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
    # Recording Stop means finish and save the captured frames. Publication
    # therefore uses the writer's normal completion policy, not capture Stop.
    with atomic_binary_writer(destination) as stream:
        frames[0].save(stream, format='GIF', save_all=True,
                       append_images=frames[1:], duration=durations,
                       loop=0, optimize=False)
