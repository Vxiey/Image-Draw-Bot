"""Normalize clipboard sources without decoding on Tk or mutating OS bitmaps."""
from PIL import Image, ImageOps

from CanvasDropPayload import (CanvasDropSource, MAX_DROP_CHARACTERS,
                               _is_http_url, _unwrap_item, parse_canvas_drop)
from ImageImport import _check, _check_source_size


def parse_text_source(text):
    """Return an existing image source for the ordinary asynchronous loader.

    Keep the drop parser's path/file-URI rules, image MIME types and bounds.
    Clipboard text must itself be a source; extracting URLs from arbitrary
    prose or HTML would broaden the previous direct-URL Paste behavior.
    Native bitmap and file-list clipboard formats remain the caller's priority.
    This function does not decode, download or grant drawing permission.
    """
    if not isinstance(text, str):
        raise ValueError('Copy an image, an image file path or a direct image URL first.')
    if len(text) > MAX_DROP_CHARACTERS:
        raise ValueError('The clipboard image text is too large.')
    if not text.strip():
        raise ValueError('Copy an image, an image file path or a direct image URL first.')
    direct = _unwrap_item(text)
    # A direct URL owns its complete query. The drag parser intentionally also
    # recognizes embedded data images; applying that ranking first could turn
    # an ordinary HTTP query parameter into a competing inline image.
    if _is_http_url(direct):
        return CanvasDropSource(direct, 'Pasted web image', 'url')
    source = parse_canvas_drop(text)
    if (source.kind == 'url' or
            (source.kind == 'data' and direct != source.source)):
        raise ValueError('Copy a direct image URL, data-image URI or image file path.')
    if source.kind == 'file':
        return source
    return CanvasDropSource(source.source, 'Pasted web image', source.kind)


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
