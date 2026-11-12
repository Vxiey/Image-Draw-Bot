"""Reproduce batch 41 against the unchanged batch 40 checkpoint.

Existing repository rasters are read or resized in memory. No image files are
created. Timing pairs alternate order; allocation tracing is a separate pass.
"""
from contextlib import closing
import gc
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc
import types
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveRegionHybrid as hybrid
import Colors
import DrawBot
from PixelAccuratePlanner import build_pixel_map
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch39_pixel_runs import public_options,stable
from test_v148_rendering_batch40_region_work import PALETTE
from test_v148_rendering_batch41_mask_runs import controls

ROOT=Path(__file__).resolve().parent
BASE='1de270273975eced1996e39e85790822cf408afe'


def historical(filename):
    source=subprocess.check_output(['git','show',f'{BASE}:{filename}'],cwd=ROOT,text=True)
    module=types.ModuleType('batch41_reference_'+filename[:-3])
    sys.modules[module.__name__]=module
    exec(compile(source,filename,'exec'),module.__dict__)
    return module


def digest(value):
    return hashlib.sha256(json.dumps(stable(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def observations(before,after,*,pairs=6,allocations=True):
    for call in (before,after):call()
    timings={'before':[],'after':[]}
    for pair in range(pairs):
        order=(('before',before),('after',after))
        if pair%2:order=order[::-1]
        for name,call in order:
            gc.collect();start=time.perf_counter();call()
            timings[name].append(round(time.perf_counter()-start,6))
    result={'pairs_seconds':timings,
        'median_seconds':{name:statistics.median(values) for name,values in timings.items()}}
    if allocations:
        peaks={}
        for name,call in (('before',before),('after',after)):
            gc.collect();tracemalloc.start();call()
            peaks[name]=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
        result['tracemalloc_peak_bytes']=peaks
    return result


def hybrid_call(module,mapped,options):
    plan=module.build_adaptive_execution(mapped,PALETTE,options,(mapped.width,mapped.height))
    try:
        comparable={key:plan[key] for key in ('execution_groups','execution_sequence','metrics')}
        comparable['metadata']={key:value for key,value in plan['metadata'].items() if key!='timings'}
        for key in ('coverage_preview','error_preview'):
            comparable[key]=hashlib.sha256(plan[key].tobytes()).hexdigest()
        return digest(comparable),len(plan['execution_sequence'])
    finally:
        plan['coverage_preview'].close();plan['error_preview'].close()


def main():
    old_hybrid=historical('AdaptiveRegionHybrid.py')
    old_accuracy=historical('PixelAccuracyEngine.py')
    old_bot=historical('DrawBot.py')
    report={'baseline':subprocess.check_output(['git','rev-parse',BASE],cwd=ROOT,text=True).strip(),
        'python':sys.version,'numpy':np.__version__,
        'method':'Alternating A/B pairs after warmup; allocation tracing separately; existing sources only.',
        'limitations':['Linux CPU measurements; no native Windows drawing-time or GPU claims.',
            'Tracemalloc is Python-tracked peak allocation, not total RSS.',
            'Pixel timing is a delivery-model prediction, not a measured deadline guarantee.',
            'Complete hybrid planner has three timing pairs and no traced-allocation pass.'],
        'cases':[]}
    with Image.open(ROOT/'golden-regression/small-detail-preservation.png') as source,source.convert('L') as gray:
        mask=np.asarray(gray)<120
    class CountedMask(np.ndarray):
        reads=0
        def __getitem__(self,key):
            CountedMask.reads+=1
            return super().__getitem__(key)
    counted=mask.view(CountedMask);reads={}
    before=lambda:old_hybrid._runs_from_mask(mask)
    after=lambda:hybrid._runs_from_mask(mask)
    assert before()==after()
    for name,module in (('before',old_hybrid),('after',hybrid)):
        CountedMask.reads=0;module._runs_from_mask(counted);reads[name]=CountedMask.reads
    report['cases'].append(dict(stage='boolean-center-runs',source='golden-regression/small-detail-preservation.png',
        size=[mask.shape[1],mask.shape[0]],exact=True,sha256=digest(after()),python_mask_reads=reads,
        **observations(before,after)))
    options=public_options(brush_px=1,profile_key='gartic-phone',browser_brush_plan=controls())
    for filename,size in (('golden-regression/small-detail-preservation.png',(192,128)),
                          ('assets/image-draw-bot-icon.png',(192,192))):
        with Image.open(ROOT/filename) as source,source.resize(size) as scaled:
            mapped=build_pixel_map(scaled,PALETTE,gpu_mode='CPU')
        before=lambda:hybrid_call(old_hybrid,mapped,options)
        after=lambda:hybrid_call(hybrid,mapped,options)
        old_value,new_value=before(),after();assert old_value==new_value
        report['cases'].append(dict(stage='complete-hybrid-builder',source=filename,size=size,
            exact=True,sha256=new_value[0],paths=new_value[1],
            **observations(before,after,pairs=3,allocations=False)))
    Colors.reset_palette()
    pixel_options=public_options(brush_px=1,delay=0,speed='Fast',
        adaptive_color_verification=False,strict_color_verification=False,
        time_budget_mode='30 sec',unlimited_time=False,max_seconds=30,manual_max_seconds=30)
    for filename in ('small-detail-preservation.png','red-bananas-texture.png'):
        row={'stage':'public-pixel-timer','source':'golden-regression/'+filename,'size':[96,64]}
        with Image.open(ROOT/'golden-regression'/filename) as source,source.resize((96,64)) as scaled:
            original=scaled.tobytes()
            for name,bot in (('before',old_bot),('after',DrawBot)):
                if name=='before':
                    with patch.dict(sys.modules,{'PixelAccuracyEngine':old_accuracy}), \
                            patch('RealSpeedBudget.load_profile',return_value=None), \
                            patch('DrawTimeCalibration.load_profile',return_value=None):
                        plan=bot.make_plan(scaled,scaled.size,dict(pixel_options))
                else:
                    with patch('RealSpeedBudget.load_profile',return_value=None), \
                            patch('DrawTimeCalibration.load_profile',return_value=None):
                        plan=bot.make_plan(scaled,scaled.size,dict(pixel_options))
                try:
                    meta=plan['options']['pixel_accuracy_meta']
                    row[name]={'paths':len(plan['execution_sequence']),
                        'pixel_accuracy_percent':meta['pixel_accuracy_percent'],
                        'protected_accuracy_percent':meta['protected_accuracy_percent'],
                        'error_pixels':meta['error_pixels'],'estimated_seconds':plan['estimate'],
                        'budget':meta['progressive_time_budget']}
                finally:close_plan(plan,scaled)
            assert scaled.tobytes()==original
        assert row['after']['error_pixels']==0
        assert row['before']['error_pixels']>row['after']['error_pixels']
        report['cases'].append(row)
    path=ROOT/'docs/v148-batch41-rendering-validation.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(path,flush=True)
    for row in report['cases']:
        print({key:row[key] for key in ('stage','source','size','median_seconds',
            'tracemalloc_peak_bytes','python_mask_reads','before','after') if key in row},flush=True)


if __name__=='__main__':main()
