"""Simple non-AI black contours: smooth, thin edges, remove isolated specks."""
import numpy as np
from PIL import Image,ImageFilter

def black_index(palette):
    for i,rgb in enumerate(palette):
        if tuple(rgb)==(0,0,0):return i
    raise ValueError('Black sketch needs a calibrated black (0,0,0) swatch. Read the palette again, or select black manually in Single-color Paint mode.')

SKETCH_DETAILS=('Simple','Balanced','Detailed')


def _remove_small_components(keep, min_component, cancelled):
    """Filter in place with storage bounded by the removable size floor."""
    h,w=keep.shape;seen=np.zeros_like(keep)
    for y in range(h):
        if cancelled():raise InterruptedError()
        for x in np.flatnonzero(keep[y]):
            if seen[y,x]:continue
            stack=[(y,int(x))];seen[y,x]=True;component=[];count=0
            while stack:
                cy,cx=stack.pop();count+=1
                if count < min_component:
                    component.append((cy,cx))
                elif count == min_component:
                    component.clear()
                if count%1024==0 and cancelled():raise InterruptedError()
                for dy,dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
                    ny,nx=cy+dy,cx+dx
                    if 0<=ny<h and 0<=nx<w and keep[ny,nx] and not seen[ny,nx]:
                        seen[ny,nx]=True;stack.append((ny,nx))
            if count<min_component:
                for cy,cx in component:keep[cy,cx]=False
    if cancelled():raise InterruptedError()
    return keep

def contour_image(image,cancelled=lambda:False,detail='Detailed'):
    if detail not in SKETCH_DETAILS:raise ValueError('Choose Simple, Balanced or Detailed sketch detail.')
    radius,floor,percentile,factor,min_component={'Simple':(2.0,40,80,.85,12),'Balanced':(1.4,32,76,.8,7),'Detailed':(1.0,24,72,.75,4)}[detail]
    if cancelled():raise InterruptedError()
    rgba=image.convert('RGBA')
    flat=Image.new('RGBA',rgba.size,'white');flat.alpha_composite(rgba)
    gray=np.asarray(flat.convert('L').filter(ImageFilter.GaussianBlur(radius)),dtype=np.float32)
    v=np.pad(gray,1,mode='edge')
    gx=(v[:-2,2:]+2*v[1:-1,2:]+v[2:,2:])-(v[:-2,:-2]+2*v[1:-1,:-2]+v[2:,:-2])
    gy=(v[2:,:-2]+2*v[2:,1:-1]+v[2:,2:])-(v[:-2,:-2]+2*v[:-2,1:-1]+v[:-2,2:])
    mag=np.hypot(gx,gy);angle=(np.rad2deg(np.arctan2(gy,gx))+180)%180
    m=np.pad(mag,1)
    directions=((0,m[1:-1,:-2],m[1:-1,2:]),(45,m[:-2,:-2],m[2:,2:]),(90,m[:-2,1:-1],m[2:,1:-1]),(135,m[:-2,2:],m[2:,:-2]))
    keep=np.zeros(gray.shape,dtype=bool)
    bins=((angle+22.5)//45).astype(np.uint8)%4
    for i,(_,before,after) in enumerate(directions):
        keep|=(bins==i)&(mag>=before)&(mag>after)
    positive=mag[mag>4]
    threshold=max(float(floor),float(np.percentile(positive,percentile))*factor) if positive.size else float(floor)
    keep&=mag>=threshold
    # Never turn the screenshot border into an artificial rectangular frame.
    keep[0,:]=False;keep[-1,:]=False;keep[:,0]=False;keep[:,-1]=False
    _remove_small_components(keep,min_component,cancelled)
    return Image.fromarray(np.where(keep,0,255).astype('uint8')).convert('RGBA')
