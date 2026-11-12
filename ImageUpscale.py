"""Bounded non-AI resampling; does not invent missing image detail."""
from PIL import Image, ImageOps
from numbers import Integral, Real
from contextlib import ExitStack, closing
MAX_PIXELS = 25_000_000

def _dimensions(size):
    try:
        values = tuple(size)
    except TypeError as error:
        raise ValueError('Invalid image dimensions.') from error
    if len(values) != 2 or any(isinstance(v, bool) or not isinstance(v, Integral) or v < 1 for v in values):
        raise ValueError('Invalid image dimensions.')
    return tuple(int(v) for v in values)

def _factor(value):
    if isinstance(value, bool) or not isinstance(value, Real) or value not in (2, 4):
        raise ValueError('Choose 2× or 4×.')
    return int(value)

def upscale_size(size, factor):
    factor = _factor(factor)
    width,height=_dimensions(size)
    target=(width*factor,height*factor)
    if target[0]*target[1]>MAX_PIXELS:
        raise ValueError('Upscaled image would exceed 25 megapixels. Choose a smaller factor.')
    return target

def suggested_factor(size):
    size=_dimensions(size)
    longest=max(size)
    factor=4 if longest<512 else 2 if longest<1024 else 1
    while factor>1:
        try: upscale_size(size,factor); return factor
        except ValueError: factor//=2
    return 1

def upscale_image(image,factor=2,method='Smooth',cancelled=lambda:False):
    factor=_factor(factor)
    target=upscale_size(image.size,factor)
    if method not in ('Smooth','Pixel art'): raise ValueError('Unknown upscale method.')
    if cancelled(): raise InterruptedError()
    result=None
    try:
        with ExitStack() as temporary:
            own=lambda value:temporary.enter_context(closing(value))
            # Import already normalizes orientation.  Pillow's no-op transpose
            # still copies the full raster; borrow that input until resampling.
            # Load first, as exif_transpose does, for formats that apply metadata
            # while decoding.  Actual rotations retain their owned temporary.
            image.load()
            source=image if image.getexif().get(274,1)==1 else own(ImageOps.exif_transpose(image))
            if cancelled(): raise InterruptedError()
            if source.mode!='RGBA': source=own(source.convert('RGBA'))
            # Recompute after EXIF rotation; preserve orientation and alpha correctly.
            target=upscale_size(source.size,factor)
            if method=='Pixel art':
                if cancelled(): raise InterruptedError()
                result=source.resize(target,Image.Resampling.NEAREST)
            else:
                # Premultiply alpha so hidden RGB cannot create dark/coloured fringes.
                premultiplied=own(source.convert('RGBa'))
                if cancelled(): raise InterruptedError()
                resized=own(premultiplied.resize(target,Image.Resampling.LANCZOS))
                if cancelled(): raise InterruptedError()
                result=resized.convert('RGBA')
            if cancelled(): raise InterruptedError()
            result.info.update(source.info)
            result.info['draw_studio_upscale']=dict(factor=factor,method=method,source_size=source.size)
            return result
    except BaseException:
        if result is not None: result.close()
        raise
