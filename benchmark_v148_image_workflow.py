"""Reproduce batch03 image-helper comparisons using generated local fixtures.

No captures, network transfers, native input or flagged executables are used.
The changed modules are loaded from the recorded local Git baseline. Baseline
shared dependencies use the current checkout, as identified in the output.
"""
from contextlib import closing
import argparse
import base64
import gc
import hashlib
import importlib
from io import BytesIO
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import types

import numpy as np
from PIL import Image,ImageDraw,__version__ as pillow_version

ROOT=Path(__file__).resolve().parent
BASELINE='2fb7abf470a4ef498df9c53f42cddda62d8b652b'


def old_module(name,revision):
    source=subprocess.check_output(['git','show',f'{revision}:{name}.py'],cwd=ROOT)
    module=types.ModuleType('_image_before_'+name);module.__file__=str(ROOT/(name+'.py'))
    sys.modules[module.__name__]=module
    exec(compile(source,module.__file__,'exec'),module.__dict__)
    return module


def fingerprint(value):
    if isinstance(value,np.ndarray):
        return {'shape':list(value.shape),'dtype':str(value.dtype),'sha256':hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value,Image.Image):
        return {'size':list(value.size),'mode':value.mode,'sha256':hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value,dict):return {key:fingerprint(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [fingerprint(item) for item in value]
    if isinstance(value,np.generic):return value.item()
    return value


def measured_pair(before,after,repeats,*,trace=True):
    expected,actual=fingerprint(before()),fingerprint(after())
    if expected!=actual:raise AssertionError('Output parity failed for benchmark fixture')
    samples=[[],[]]
    for _ in range(repeats):
        for index,operation in enumerate((before,after)):
            started=time.perf_counter();operation()
            samples[index].append(1000*(time.perf_counter()-started))
    result={'before_samples_ms':samples[0],'after_samples_ms':samples[1],
            'before_median_ms':statistics.median(samples[0]),'after_median_ms':statistics.median(samples[1]),
            'exact_output_parity':True,'output_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest()}
    if trace:
        for name,operation in (('before',before),('after',after)):
            gc.collect();tracemalloc.start()
            try:
                operation();result[name+'_peak_python_bytes']=tracemalloc.get_traced_memory()[1]
            finally:tracemalloc.stop()
    return result


def measure(revision=BASELINE,repeats=5):
    if type(repeats) is not int or repeats<1:raise ValueError('Repeats must be a positive integer')
    names=('BackgroundRemoval','DrawingStyleProfiles','SubjectFocus','ImageFormatInfo','DrawBot')
    before={name:old_module(name,revision) for name in names}
    after={name:importlib.import_module(name) for name in names}
    result={'baseline':revision,'python':sys.version.split()[0],'platform':platform.platform(),
            'numpy':np.__version__,'pillow':pillow_version,'repeats':repeats,
            'method':'One warm/parity pair, alternating before/after elapsed samples, separate Python traced peaks after garbage collection.',
            'scope':'Synthetic CPU helpers only; not total drawing, UI, network, GPU or Windows input performance. Python tracing excludes most native Pillow allocation. Baseline changed modules import current shared dependencies.',
            'after_source_sha256':{name:hashlib.sha256((ROOT/(name+'.py')).read_bytes()).hexdigest()
                                   for name in (*names,'ImageImport','ImageGeometry')},'measurements':{}}
    output=result['measurements'];rng=np.random.default_rng(1480301)
    pixels=rng.integers(0,256,(700,900,3)).astype(np.float32)
    centers=np.array([[0,0,0],[255,255,255],[190,45,30],[20,120,210]],np.float32)
    spreads=np.array([6,12,18,24],np.float32)
    calls=[lambda module=module:module._candidate_maps(pixels,centers,spreads,'Balanced','Auto')
           for module in (before['BackgroundRemoval'],after['BackgroundRemoval'])]
    output['cluster_minima_900x700_four_centres']={**measured_pair(*calls,repeats),
        'parameters':{'size':[900,700],'centres':centers.tolist(),'spreads':spreads.tolist(),'seed':1480301}}

    pixels=np.full((180,240,3),255,np.float32);edge=np.zeros((180,240),np.float32)
    calls=[lambda module=module:module._grow(pixels,np.array([[255]*3],np.float32),np.array([10]),'Balanced','Auto',edge,lambda:False)
           for module in (before['BackgroundRemoval'],after['BackgroundRemoval'])]
    output['background_flood_240x180_white']={**measured_pair(*calls,repeats,trace=False),
        'parameters':{'size':[240,180],'background':'white','edge':0},'memory_scope':'Timing only; Python flood tracing would dominate this fixture.'}

    mask=np.zeros((250,350),np.uint8);mask[25:225,40:300]=1
    calls=[lambda module=module:module._largest_component(mask,lambda:False)
           for module in (before['BackgroundRemoval'],after['BackgroundRemoval'])]
    output['largest_component_350x250']={**measured_pair(*calls,repeats),
        'parameters':{'size':[350,250],'rectangle':[40,25,300,225]}}

    with closing(Image.fromarray(rng.integers(0,256,(96,128,3),dtype=np.uint8))) as tile:
        source=tile.resize((4000,3000),Image.Resampling.NEAREST)
    with closing(source):
        calls=[lambda module=module:module._metrics(source) for module in (before['DrawingStyleProfiles'],after['DrawingStyleProfiles'])]
        output['drawing_style_4000x3000_rgb']={**measured_pair(*calls,repeats),
            'parameters':{'size':[4000,3000],'source':'96x128 RGB tile enlarged with NEAREST','seed':1480301}}

    with closing(Image.new('RGB',(2000,1500),'white')) as source:
        ImageDraw.Draw(source).rectangle((600,400,1399,1099),fill='red')
        calls=[lambda module=module:module.subject_mask(source) for module in (before['SubjectFocus'],after['SubjectFocus'])]
        output['subject_mask_2000x1500_rgb']={**measured_pair(*calls,repeats),
            'parameters':{'size':[2000,1500],'subject':'red rectangle 600,400,1399,1099 on white'}}

    with closing(Image.new('RGBA',(240,180),'white')) as source:
        draw=ImageDraw.Draw(source);draw.ellipse((70,35,170,150),fill='#2c93b5');draw.rectangle((110,60,125,120),fill='#b24c1c')
        def remove(module):
            value=module.remove_background(source)
            with closing(value.image):return {'image':fingerprint(value.image),'metadata':value.metadata}
        calls=[lambda module=module:remove(module) for module in (before['BackgroundRemoval'],after['BackgroundRemoval'])]
        output['complete_background_removal_240x180']={**measured_pair(*calls,repeats,trace=False),
            'parameters':{'size':[240,180],'subject':'blue ellipse and rust rectangle on white'},
            'memory_scope':'Timing only; output pixel bytes and full metadata are compared.'}

    with closing(Image.new('P',(3000,2000),0)) as source:
        source.putpalette([component for level in range(256) for component in (level,level,level)])
        source.info['transparency']=bytes([255,0]);source.putpixel((2999,1999),1)
        calls=[lambda module=module:module.image_label(source,'image') for module in (before['ImageFormatInfo'],after['ImageFormatInfo'])]
        output['palette_image_label_3000x2000']={**measured_pair(*calls,repeats),
            'parameters':{'size':[3000,2000],'palette':'greyscale','transparency':'index 1 only, used at final pixel'}}

    with closing(Image.new('RGBA',(10,8),(12,34,56,120))) as source:
        buffer=BytesIO();source.save(buffer,format='PNG')
    data=buffer.getvalue()+bytes(8*1024*1024)
    uri='data:image/png;base64,'+base64.b64encode(data).decode('ascii')
    def imported(module):
        with closing(module.load_image(uri)) as image:return (fingerprint(image),image.info)
    calls=[lambda module=module:imported(module) for module in (before['DrawBot'],after['DrawBot'])]
    output['base64_import_8mib_encoded_source']={**measured_pair(*calls,repeats),
        'parameters':{'image_size':[10,8],'trailing_fixture_bytes':8*1024*1024,'source_bytes':len(data)}}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE);parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch03-image-benchmarks.json')
    args=parser.parse_args();result=measure(args.baseline,args.repeats)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:{name:value[name] for name in ('before_median_ms','after_median_ms','exact_output_parity')}
                      for key,value in result['measurements'].items()},indent=2))
