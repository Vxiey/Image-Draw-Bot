"""Contrast the visible source while retaining its original opacity."""
from contextlib import closing
import math

from PIL import Image, ImageStat


def _contrast_rgb(rgb, factor):
    """Pillow's Contrast formula with explicit ownership of its two scratch images."""
    with closing(rgb.convert('L')) as luminance:
        mean = int(ImageStat.Stat(luminance).mean[0] + .5)
    with closing(Image.new('RGB', rgb.size, (mean, mean, mean))) as neutral:
        return Image.blend(neutral, rgb, factor)


def enhance_contrast(image, factor, *, cancelled=lambda: False):
    """Return an owned RGBA image; borrow and preserve the caller's source.

    Pillow's RGB contrast mean must be measured from the visible white-canvas
    composite. RGB hidden by alpha zero must not change visible ink. For a
    translucent pixel, transfer the visible delta back to its original channels
    with the established alpha-preserving filter policy; gamut clipping still
    applies and its opacity does not change.
    """
    factor = float(factor)
    if not math.isfinite(factor):
        raise ValueError('Contrast must be finite.')
    if cancelled():
        raise InterruptedError()
    source = image.convert('RGBA')
    result = None
    try:
        if cancelled():
            raise InterruptedError()
        if factor == 1.0:
            result, source = source, None
        elif source.getextrema()[3] == (255, 255):
            with closing(source.convert('RGB')) as rgb:
                with closing(_contrast_rgb(rgb, factor)) as processed:
                    result = processed.convert('RGBA')
        else:
            with closing(Image.new('RGBA', source.size, 'white')) as backdrop:
                backdrop.alpha_composite(source)
                with closing(backdrop.convert('RGB')) as visible:
                    with closing(_contrast_rgb(visible, factor)) as processed:
                        from AdaptiveDetail import _restore_source_alpha
                        result = _restore_source_alpha(source, visible, processed, cancelled)
        if cancelled():
            raise InterruptedError()
        return result
    except BaseException:
        if result is not None:
            result.close()
        raise
    finally:
        if source is not None:
            source.close()
