"""Positive bounded thumbnail geometry without allocating an image copy."""
from math import ceil, floor
from numbers import Integral


def thumbnail_size(size, bounds):
    """Match Pillow's nearest aspect-ratio choice without enlarging the source."""
    try:
        width,height=size;limit_w,limit_h=bounds
    except (TypeError,ValueError) as error:
        raise ValueError('Image geometry needs two positive integer dimensions.') from error
    if any(isinstance(v,bool) or not isinstance(v,Integral) or not 1<=v<=2**31-1
           for v in (width,height,limit_w,limit_h)):
        raise ValueError('Image geometry needs two positive integer dimensions.')
    width,height,limit_w,limit_h=map(int,(width,height,limit_w,limit_h))
    if width<=limit_w and height<=limit_h:return width,height
    aspect=width/height
    if limit_w/limit_h>=aspect:
        ideal=limit_h*aspect
        chosen=min((floor(ideal),ceil(ideal)),key=lambda n:abs(aspect-n/limit_h))
        return max(1,chosen),limit_h
    ideal=limit_w/aspect
    chosen=min((floor(ideal),ceil(ideal)),key=lambda n:abs(aspect-limit_w/n) if n else float('inf'))
    return limit_w,max(1,chosen)
