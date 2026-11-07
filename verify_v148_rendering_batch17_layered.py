"""Historical R1701 planner parity gate; no CPU timing or accuracy-uplift claim."""
from contextlib import closing
from hashlib import sha256
import argparse
import itertools
import json
from pathlib import Path
import subprocess
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
import AdvancedColor as current
import DrawBot
import numpy as np
from PIL import Image
from AutoSketchBudget import _trial_images
from ColorFidelity import COLOR_FIDELITY_MODES
from PreviewQuality import full_preview_options
from test_v148_rendering_batch17_layered_diagnostics import calibrated, BLACK_WHITE, plan_options



def verify(baseline, destination):
    current_hash = sha256((ROOT/'AdvancedColor.py').read_bytes()).hexdigest()
    source = subprocess.check_output(['git', 'show', baseline + ':AdvancedColor.py'], cwd=ROOT)
    historical = types.ModuleType('HistoricalAdvancedColorBatch17')
    exec(compile(source, 'e87bc:AdvancedColor.py', 'exec'), historical.__dict__)

    def snapshot(value, path=()):
        if isinstance(value, Image.Image):
            return {'image': value.mode, 'size': value.size, 'sha256': sha256(value.tobytes()).hexdigest()}
        if isinstance(value, dict):
            return {key: snapshot(item, path + (key,)) for key, item in value.items()
                    if key not in ('color_fidelity_diagnostics', 'performance_profile', '_performance_profile')
                    and not (key == 'planning_seconds' and path and path[-1] == 'performance')}
        if isinstance(value, (tuple, list)):
            return [snapshot(item, path) for item in value]
        return value

    def digest(value):
        return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def differences(a,b,path=''):
        if isinstance(a,dict) and isinstance(b,dict):
            return [item for key in a.keys() | b.keys()
                    for item in differences(a.get(key),b.get(key),path+'/'+key)]
        if isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            return [item for i,(left,right) in enumerate(zip(a,b))
                    for item in differences(left,right,path+'/'+str(i))]
        return [] if a==b else [(path,a,b)]

    records = []
    data = np.array([(90,90,90,255),(170,40,110,255),(0,0,0,128),
                     (255,255,255,255),(240,10,60,0),(20,120,240,210)], dtype=np.uint8)
    data = data[np.random.default_rng(1481701).integers(0, len(data), (8,12))]
    modes = [('Layered color mix','Off'),('Layered color mix','Light shading'),
             ('Layered color mix','Dual-color mix'),('Layered color mix','Full color mix'),
             ('Perceptual match','Full color mix')]
    for palette in (BLACK_WHITE, BLACK_WHITE[::-1]):
        with calibrated(palette), closing(Image.fromarray(data)) as image:
            original = image.tobytes()
            for fidelity, (rendering,layers), lines, skip in itertools.product(
                    COLOR_FIDELITY_MODES, modes, (False,True), (False,True)):
                options = dict(lines=lines,skip_white=skip,color_rendering=rendering,
                               color_layers=layers,color_fidelity=fidelity,gpu_mode='CPU')
                old_groups, old_meta = historical.build_color_strokes(image, **options)
                new_groups, new_meta = current.build_color_strokes(image, **options)
                assert old_groups == new_groups
                assert snapshot(old_meta) == snapshot(new_meta)
                assert original == image.tobytes()
                records.append(digest((old_groups,snapshot(old_meta))))

    parallel_rows = []
    with calibrated(), closing(Image.new('RGBA',(256,196),(90,90,90,255))) as image:
        for engine, workers in (('Auto',1),('Threads',2)):
            options = dict(lines=True,skip_white=False,color_rendering='Layered color mix',
                           color_layers='Full color mix',gpu_mode='CPU',cpu_engine=engine,cpu_workers=workers)
            old = historical.build_color_strokes(image, **options)
            new = current.build_color_strokes(image, **options)
            assert old[0] == new[0]
            assert snapshot(old[1]) == snapshot(new[1])
            parallel_rows.append({'engine':engine,'workers':workers,'digest':digest(snapshot(new))})

    public_rows = []
    with calibrated(), patch('ResourceAllocation.available_ram_mb',return_value=8192), \
            patch('ResourceAllocation.logical_cpu_count',return_value=8):
        for full, size, area in itertools.product((False,True), ((12,8),(41,29)), ((96,64),)):
            options = plan_options()
            options.update(cpu_workers='1',ram_budget='512 MB')
            if full: options = full_preview_options(options, size)
            with closing(Image.new('RGBA',size,(90,90,90,255))) as image:
                plans = []
                try:
                    for implementation in (historical.build_color_strokes,current.build_color_strokes):
                        with patch('DrawBot.build_color_strokes',implementation):
                            plans.append(DrawBot.make_plan(image,area,options))
                    old, new = map(snapshot, plans)
                    assert old == new, differences(old,new)
                    public_rows.append({'full_preview':full,'source_size':size,'area':area,
                                        'plan_digest':digest(new),'count':plans[1]['count'],
                                        'before':plans[0]['options']['advanced_color_meta']['color_fidelity_diagnostics'],
                                        'after':plans[1]['options']['advanced_color_meta']['color_fidelity_diagnostics']})
                finally:
                    for plan in plans:
                        for owned in _trial_images(plan):
                            if owned is not image: owned.close()

    report = {'baseline_commit':baseline,'historical_advanced_color_sha256':sha256(source).hexdigest(),
              'current_advanced_color_sha256':sha256((ROOT/'AdvancedColor.py').read_bytes()).hexdigest(),
              'comparison_exclusions':['color_fidelity_diagnostics','performance_profile','_performance_profile',
                  'preview_diagnostics.performance.planning_seconds',
                  'options.preview_diagnostics_meta.performance.planning_seconds'],
              'resource_probe_controls':{'available_ram_mb':8192,'logical_cpu_count':8},
              'serial_build_pairs':len(records),'serial_digest':digest(records),
              'parallel_pairs':parallel_rows,'public_plan_pairs':public_rows,
              'all_pairs_exact_except_diagnostics_and_profiler':True,
              'timing_claim':None}
    assert sha256((ROOT/'AdvancedColor.py').read_bytes()).hexdigest() == current_hash
    assert report['current_advanced_color_sha256'] == current_hash
    destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='e87bcf1b783b33ff866c2188e10c8b5d22a22707')
    parser.add_argument('--output', type=Path,
                        default=ROOT/'docs/v148-batch17-layered-diagnostics-evidence.json')
    args = parser.parse_args(argv)
    report = verify(args.baseline, args.output)
    print(json.dumps({'serial_pairs': report['serial_build_pairs'],
                      'parallel_pairs': len(report['parallel_pairs']),
                      'public_plan_pairs': len(report['public_plan_pairs']),
                      'evidence': str(args.output),
                      'sha256': sha256(args.output.read_bytes()).hexdigest()}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
