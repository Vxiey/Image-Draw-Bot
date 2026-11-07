"""Bounded CUDA palette matching: one thread per pixel, no pixel x palette cube.

The scalar score matches UniversalGpuAcceleration's NumPy reference. CuPy is
imported only by the caller, so CPU-only installations need no CUDA dependency.
"""
from functools import lru_cache

import numpy as np

# No fast-math: preserve close color decisions and first-candidate tie breaking.
PREAMBLE = r'''
__device__ float ds_linear(float c) {
    return c <= .04045f ? c / 12.92f : powf((c + .055f) / 1.055f, 2.4f);
}
__device__ float ds_hue(float a, float b) {
    float h = atan2f(b, a) * 57.29577951308232f;
    return h < 0.f ? h + 360.f : h;
}
'''
OPERATION = r'''
float r = rgb[i*3], g = rgb[i*3+1], b = rgb[i*3+2];
float L=0.f, A=0.f, B=0.f, C=0.f, H=0.f;
if (perceptual) {
    float lr=ds_linear(r/255.f), lg=ds_linear(g/255.f), lb=ds_linear(b/255.f);
    float l=cbrtf(.4122214708f*lr+.5363325363f*lg+.0514459929f*lb);
    float m=cbrtf(.2119034982f*lr+.6806995451f*lg+.1073969566f*lb);
    float s=cbrtf(.0883024619f*lr+.2817188376f*lg+.6299787005f*lb);
    L=.2104542553f*l+.7936177850f*m-.0040720468f*s;
    A=1.9779984951f*l-2.4285922050f*m+.4505937099f*s;
    B=.0259040371f*l+.7827717662f*m-.8086757660f*s;
    C=hypotf(A,B)*100.f; H=ds_hue(A,B);
}
float best=INFINITY, best_custom=INFINITY;
short chosen=ids[0], custom_chosen=ids[0];
for (int p=0; p<count; ++p) {
    float dist;
    if (perceptual) {
        float dl=L-lab[p*3], da=A-lab[p*3+1], db=B-lab[p*3+2];
        dist=sqrtf(dl*dl+da*da+db*db)*100.f;
        if (fidelity) {
            float srcL=L*100.f, palL=lab[p*3]*100.f;
            float palC=hypotf(lab[p*3+1],lab[p*3+2])*100.f;
            float hd=fabsf(H-ds_hue(lab[p*3+1],lab[p*3+2]));
            float hue=fminf(hd,360.f-hd);
            if (fminf(C,palC)<2.5f) hue=0.f;
            float light=fabsf(srcL-palL), dark=fmaxf(srcL-palL,0.f);
            float chroma=fabsf(C-palC), bright=1.f+fmaxf(srcL-52.f,0.f)/80.f;
            float neutral=(C>=5.f && palC<fmaxf(2.5f,C*.28f))?C-palC:0.f;
            float hex=(C>=5.f)?fmaxf(hue-45.f,0.f):0.f;
            float hext=(C>=5.f)?fmaxf(hue-85.f,0.f):0.f;
            if (fidelity==1)
                dist+=light*.10f+dark*.24f*bright+chroma*.055f+hue*.010f+neutral*.18f+hex*.035f+hext*.060f;
            else
                dist+=light*.22f+dark*.55f*bright+chroma*.115f+hue*.026f+neutral*.32f+hex*.080f+hext*.120f;
        }
    } else {
        float dr=r-palette[p*3], dg=g-palette[p*3+1], db=b-palette[p*3+2];
        dist=sqrtf((dr*dr+dg*dg+db*db)/3.f)/255.f*100.f;
    }
    if (dist<best) { best=dist; chosen=ids[p]; }
    if (custom[p] && dist<best_custom) { best_custom=dist; custom_chosen=ids[p]; }
}
result = (custom_first && best_custom<=best*1.06f+.0006f)?custom_chosen:chosen;
'''


@lru_cache(maxsize=1)
def _kernel(cp):
    return cp.ElementwiseKernel(
        'raw float32 rgb, raw float32 palette, raw float32 lab, raw int16 ids, '
        'raw uint8 custom, int32 count, int32 perceptual, int32 fidelity, int32 custom_first',
        'int16 result', OPERATION, 'ds_palette_match_fused_v1', preamble=PREAMBLE, options=('--fmad=false',))


def match(cp, rgb, palette, palette_lab, ids, custom, *, perceptual, fidelity,
          custom_first, cancelled):
    """Use at most 16 MiB of input/output tile data, with cancellation per tile.

    Device selection is owned by the caller. No global pool settings are changed;
    this respects existing memory limits and avoids interfering with previews.
    """
    kernel = _kernel(cp)
    flat = np.ascontiguousarray(rgb, dtype=np.float32).reshape(-1, 3)
    output = np.empty(flat.shape[0], dtype=np.int16)
    # Account for live pool allocations, not just driver free memory.
    free_bytes, _ = cp.cuda.runtime.memGetInfo()
    pool = cp.get_default_memory_pool()
    reusable = max(0, pool.total_bytes() - pool.used_bytes())
    available = int(free_bytes) + reusable
    limit = pool.get_limit()
    if limit:
        available = min(available, max(0, limit - pool.used_bytes()))
    palette_bytes = int(palette.nbytes + palette_lab.nbytes + ids.nbytes + custom.nbytes)
    budget = min(16 * 1024 * 1024, max(0, available // 4 - palette_bytes))
    # Bound kernel duration as well as memory for unusually large palettes.
    chunk = min(262144, 8_000_000 // max(1, len(ids)), budget // 14)
    if chunk < 1:
        raise MemoryError('Insufficient CUDA workspace for palette tile')
    p = cp.asarray(palette, dtype=cp.float32)
    lab = cp.asarray(palette_lab, dtype=cp.float32)
    cid = cp.asarray(ids, dtype=cp.int16)
    flags = cp.asarray(custom, dtype=cp.uint8)
    device_input = cp.empty((chunk, 3), dtype=cp.float32)
    device_output = cp.empty(chunk, dtype=cp.int16)
    for start in range(0, len(flat), chunk):
        if cancelled():
            raise InterruptedError()
        end = min(len(flat), start + chunk)
        n = end - start
        device_input[:n].set(flat[start:end])
        kernel(device_input[:n], p, lab, cid, flags, np.int32(len(ids)),
               np.int32(perceptual), np.int32(fidelity), np.int32(custom_first),
               device_output[:n])
        # Blocking download synchronizes the current stream, including non-default streams.
        device_output[:n].get(out=output[start:end])
    return output.reshape(rgb.shape[:-1])
