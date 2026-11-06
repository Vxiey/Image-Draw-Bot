"""Paired batch04 application helper measurements with exact output checks."""
from contextlib import closing
from dataclasses import asdict
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
import tempfile
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

from benchmark_v148_image_workflow import old_module, measured_pair

ROOT=Path(__file__).resolve().parent
BASELINE='1d48eabaf349a5fd8049a2c96ef5426745c3078c'


def measure(revision=BASELINE,repeats=5):
    if type(repeats) is not int or repeats<1:raise ValueError('Repeats must be a positive integer.')
    names=('AutoDrawing','PicturePaletteRefinement','DominantHuePreservation','SessionRecovery')
    before={name:old_module(name,revision) for name in names}
    after={name:importlib.import_module(name) for name in names}
    result={'baseline':revision,'python':sys.version.split()[0],'platform':platform.platform(),
        'numpy':np.__version__,'pillow':pillow_version,'repeats':repeats,
        'method':'Warm parity pair, alternating before/after elapsed samples; separate Python traced allocation peak.',
        'scope':'Generated CPU helper fixtures only; not total drawing speed, Windows input or total process RAM. Python tracing excludes most native Pillow buffers. Baseline modules use current shared dependencies.',
        'after_source_sha256':{name:hashlib.sha256((ROOT/(name+'.py')).read_bytes()).hexdigest()
                              for name in (*names,'ColorMatchingEngine','ImageSampling','ImageGeometry')},
        'measurements':{}}
    out=result['measurements'];rng=np.random.default_rng(1480401)
    with closing(Image.fromarray(rng.integers(0,256,(96,128,3),dtype=np.uint8))) as tile:
        source=tile.resize((4000,3000),Image.Resampling.NEAREST)
    with closing(source):
        calls=[lambda module=module:module._image_statistics(source)
               for module in (before['AutoDrawing'],after['AutoDrawing'])]
        out['automatic_statistics_4000x3000_rgb']={**measured_pair(*calls,repeats),
            'parameters':{'size':[4000,3000],'seed':1480401,'source':'96x128 RGB tile enlarged with NEAREST'}}
        colors=((0,0,0),(255,255,255),(230,30,40),(30,90,210),(40,190,60),(230,210,30))
        calls=[lambda module=module:module.refine_picture_palette(source,colors,12)
               for module in (before['PicturePaletteRefinement'],after['PicturePaletteRefinement'])]
        out['palette_refinement_4000x3000_rgb']={**measured_pair(*calls,repeats),
            'parameters':{'size':[4000,3000],'seed':1480401,'colors':colors,'max_colors':12}}
    colors=[tuple(map(int,color)) for color in rng.integers(0,256,(16000,3))]
    weights=rng.integers(1,100,16000).tolist()
    calls=[lambda module=module:[asdict(row) for row in module.summarize_hue_families(colors,weights)]
           for module in (before['DominantHuePreservation'],after['DominantHuePreservation'])]
    out['dominant_hue_summary_16000_colors']={**measured_pair(*calls,repeats),
        'parameters':{'colors':16000,'seed':1480401,'weight_range':[1,99]}}
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        for index in range(10000):(root/f'unrelated-{index}.txt').touch()
        def clean(module):
            with patch.object(module,'IMAGE_FILE',root/'last-image.png'),patch.object(module,'_read_state',return_value=None):
                return module._clean_old_images(set())
        calls=[lambda module=module:clean(module) for module in (before['SessionRecovery'],after['SessionRecovery'])]
        out['recovery_cleanup_10000_unrelated_files']={**measured_pair(*calls,repeats),
            'parameters':{'entries':10000,'deleted_files':0}}
        if len(list(root.iterdir()))!=10000:raise AssertionError('Cleanup removed unrelated files')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE);parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch04-application-benchmarks.json')
    args=parser.parse_args();result=measure(args.baseline,args.repeats)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:{name:value[name] for name in ('before_median_ms','after_median_ms','exact_output_parity',
                                                      'before_peak_python_bytes','after_peak_python_bytes')}
                     for key,value in result['measurements'].items()},indent=2))
