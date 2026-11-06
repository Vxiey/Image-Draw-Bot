"""Map unsigned 16-bit grayscale into the planner's 8-bit source range."""
from contextlib import closing
from numbers import Integral

import numpy as np
from PIL import Image

UNSIGNED_16BIT_MODES = frozenset(('I;16','I;16L','I;16B','I;16N'))
_TILE_WIDTH = 1024
_TILE_PIXELS = 262_144


def grayscale_8bit(image, *, cancelled=lambda: False):
    """Return owned L/LA pixels using the full 0..65535 unsigned range.

    This is fixed-range quantization, not per-image contrast stretching. A
    transparency key is compared before quantization so nearby opaque values
    that round to the same 8-bit gray cannot accidentally become transparent.
    The input and its metadata are borrowed; numeric scratch is tile-bounded.
    """
    if image.mode not in UNSIGNED_16BIT_MODES:
        raise ValueError('Expected unsigned 16-bit grayscale pixels.')
    if cancelled():raise InterruptedError('Image bit-depth conversion cancelled.')
    key=image.info.get('transparency')
    if key is not None:
        if isinstance(key,bool) or not isinstance(key,Integral) or not 0<=key<=65535:
            raise ValueError('The 16-bit image contains an invalid transparency value.')
        key=int(key)
    result=Image.new('LA' if key is not None else 'L',image.size)
    try:
        tile_width=min(_TILE_WIDTH,image.width)
        tile_height=max(1,_TILE_PIXELS//max(1,tile_width))
        for top in range(0,image.height,tile_height):
            for left in range(0,image.width,tile_width):
                if cancelled():raise InterruptedError('Image bit-depth conversion cancelled.')
                box=(left,top,min(image.width,left+tile_width),min(image.height,top+tile_height))
                with closing(image.crop(box)) as tile:
                    raw=np.asarray(tile)
                    values=raw.astype(np.uint32)
                    values+=128
                    values//=257
                    gray=values.astype(np.uint8)
                    del values
                    with closing(Image.fromarray(gray)) as part:
                        if key is None:
                            result.paste(part,(left,top))
                        else:
                            alpha=np.where(raw==key,0,255).astype(np.uint8)
                            with closing(Image.fromarray(alpha)) as mask,closing(Image.merge('LA',(part,mask))) as rgba:
                                result.paste(rgba,(left,top))
        result.info.update(image.info)
        result.info.pop('transparency',None)
        result.info['draw_studio_bit_depth']='16-bit grayscale mapped to 8-bit'
        if cancelled():raise InterruptedError('Image bit-depth conversion cancelled.')
        return result
    except BaseException:
        result.close()
        raise
