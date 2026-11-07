"""Window geometry in logical pixels, without sending desktop input."""
import math
from numbers import Integral,Real


def window_size(screen_width,screen_height,*,preferred=(1180,800),margin=(60,90),scale=1.0):
    if isinstance(scale,bool) or not isinstance(scale,Real):
        raise ValueError('Window scaling must be a finite positive number.')
    try:scale=float(scale)
    except (TypeError,ValueError,OverflowError) as error:raise ValueError('Invalid window scaling.') from error
    if not math.isfinite(scale) or scale<=0:raise ValueError('Invalid window scaling.')
    values=(screen_width,screen_height,*preferred,*margin)
    if len(preferred)!=2 or len(margin)!=2 or any(isinstance(v,bool) or not isinstance(v,Integral) for v in values):
        raise ValueError('Window dimensions must be integers.')
    if min(screen_width,screen_height,*preferred)<1 or min(margin)<0:
        raise ValueError('Window dimensions must be positive.')
    available=(max(1,int(screen_width/scale-margin[0])),
               max(1,int(screen_height/scale-margin[1])))
    return min(int(preferred[0]),available[0]),min(int(preferred[1]),available[1])


def fit_window(window,preferred=(1180,800),minimum=(480,400),margin=(60,90)):
    """Fit both geometry and minimum size after CustomTkinter's DPI scaling."""
    scale=1.0
    getter=getattr(window,'_get_window_scaling',None)
    if callable(getter):
        try:
            value=float(getter())
            if math.isfinite(value) and value>0:scale=value
        except (TypeError,ValueError,OverflowError):pass
    size=window_size(window.winfo_screenwidth(),window.winfo_screenheight(),
                     preferred=preferred,margin=margin,scale=scale)
    if len(minimum)!=2 or any(isinstance(v,bool) or not isinstance(v,Integral) or v<1 for v in minimum):
        raise ValueError('Window minimum size must contain positive integers.')
    window.minsize(*(min(int(requested),actual) for requested,actual in zip(minimum,size)))
    window.geometry(f'{size[0]}x{size[1]}')
    return size


def compact_layout(width):return width<1050
