"""Prepare an OS clipboard bitmap without Tk access or borrowed-image mutation."""
from PIL import Image, ImageOps

from ImageImport import _check, _check_source_size


def prepare_bitmap(source, cancelled=lambda: False):
    """Return an owned, oriented sRGB RGBA image; the OS snapshot stays borrowed."""
    if not isinstance(source, Image.Image):
        raise ValueError('The clipboard does not contain a bitmap image.')
    _check(cancelled)
    _check_source_size(source.width, source.height, 25_000_000)
    oriented = result = None
    try:
        oriented = ImageOps.exif_transpose(source)
        _check(cancelled)
        oriented.info.pop('draw_studio_color_managed', None)
        oriented.info.pop('draw_studio_bit_depth', None)
        from SourcePixelDepth import UNSIGNED_16BIT_MODES
        if oriented.info.get('icc_profile') or oriented.mode in UNSIGNED_16BIT_MODES:
            from ImageColorManagement import srgb_source
            result = srgb_source(oriented, cancelled=cancelled)
        elif oriented.mode == 'RGBA':
            result, oriented = oriented, None
        else:
            result = oriented.convert('RGBA')
        result.info.pop('draw_studio_format', None)
        _check(cancelled)
        return result
    except BaseException:
        if result is not None:
            result.close()
        raise
    finally:
        if oriented is not None:
            oriented.close()
