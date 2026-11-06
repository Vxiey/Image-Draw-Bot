"""Describe decoded pixels without guessing an encoded format from a suffix."""
from contextlib import closing

from PIL import Image

_ALPHA_SCAN_PIXELS = 262_144


def _has_transparency(image):
    if not image.width or not image.height:
        return False
    bands = image.getbands()
    alpha_band = next((i for i, band in enumerate(bands) if band in ('A', 'a')), None)
    if alpha_band is not None:
        return image.getextrema()[alpha_band][0] < 255
    palette_alpha = (image.mode == 'P' and image.palette is not None and
                     image.palette.mode == 'RGBA')
    if 'transparency' not in image.info and not palette_alpha:
        return False
    if image.mode == 'P':
        # Convert only the 256 possible palette entries. Unused transparent
        # colours do not make an otherwise opaque image transparent.
        with closing(Image.new('P', (256, 1))) as probe:
            if image.palette is not None:
                probe.putpalette(image.getpalette('RGBA'), rawmode='RGBA')
            probe.putdata(range(256))
            if 'transparency' in image.info:
                probe.info['transparency'] = image.info['transparency']
            with closing(probe.convert('RGBA')) as converted, closing(converted.getchannel('A')) as alpha:
                return any(count and value < 255 for count, value in zip(image.histogram(), alpha.tobytes()))
    # RGB/greyscale transparency keys need decoded-pixel comparisons. Keep
    # conversion bounded and stop at the first visible transparency evidence.
    rows = max(1, _ALPHA_SCAN_PIXELS // image.width)
    for top in range(0, image.height, rows):
        with closing(image.crop((0, top, image.width, min(image.height, top + rows)))) as part:
            with closing(part.convert('RGBA')) as converted:
                if converted.getextrema()[3][0] < 255:
                    return True
    return False


def image_label(image, name):
    encoded = image.info.get('draw_studio_format') or image.format or 'Clipboard / decoded pixels'
    transparency = 'transparent pixels' if _has_transparency(image) else 'no transparency'
    managed = ' · sRGB from embedded color profile' if image.info.get('draw_studio_color_managed') else ''
    depth = ' · 16-bit grayscale mapped to 8-bit' if image.info.get('draw_studio_bit_depth') else ''
    return f'{name} · {encoded} · {image.width} × {image.height} · {transparency}{managed}{depth}'
