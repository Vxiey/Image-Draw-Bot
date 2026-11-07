"""Isolated batch14 CPU work reductions with complete public-plan parity.

Historical functions are loaded from the recorded Git source; all callers and
other dependencies remain current on both sides. Six balanced AB/BA pairs and
separate traced allocation probes check complete outputs on every invocation.
"""
import argparse
import ast
import builtins
from contextlib import ExitStack, closing
import copy
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import DrawBot
import ExecutionCostModel as costs
import PixelStrokeEngine as strokes
from RasterIdentity import canonical_pixels_from_paths, canonical_pixels_from_runs
from benchmark_v148_image_workflow import fingerprint
from benchmark_v148_stroke_optimizer import paired
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch14_prepared_cost import components_fixture


ROOT=Path(__file__).resolve().parent
BASELINE='f7b561f479d94f307924dbc779e5c8e365422f8d'
VOLATILE_PATHS={
    ('performance_profile',), ('options','_performance_profile'),
    ('preview_diagnostics','performance','planning_seconds'),
    ('options','preview_diagnostics_meta','performance','planning_seconds'),
    ('options','pixel_stroke_meta','planning_stage_seconds'),
}


def historical_function(name, revision):
    source=subprocess.check_output(['git','show',f'{revision}:PixelStrokeEngine.py'],cwd=ROOT).decode('utf-8')
    node=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name==name)
    scope=dict(vars(strokes))
    exec(compile(ast.Module(body=[node],type_ignores=[]),f'{revision}:PixelStrokeEngine.{name}','exec'),scope)
    return scope[name],hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest()


def comparable_plan(value, path=()):
    if isinstance(value,dict):
        return {key:comparable_plan(item,(*path,key)) for key,item in value.items()
                if (*path,key) not in VOLATILE_PATHS}
    if isinstance(value,(tuple,list)):
        return [comparable_plan(item,path) for item in value]
    return fingerprint(value)


def parity_cases(before_merge, before_schedule):
    cases=0
    for seed in range(50):
        rng=random.Random(seed)
        runs=[(x,y,x+rng.randrange(1,15),y) for y in range(-2,20) if rng.random()>.1
              for x in sorted(rng.randrange(-8,40) for _ in range(rng.randrange(1,10)))]
        rng.shuffle(runs);original=copy.deepcopy(runs)
        ink=canonical_pixels_from_runs(runs)
        for cap in (2,3,5,10,25,480):
            for rows in (1,3,96):
                settings=dict(max_points_per_path=cap,max_rows_per_path=rows)
                expected=before_merge(runs,**settings)
                actual=strokes._merge_horizontal_runs_lossless(runs,**settings)
                if actual!=expected or canonical_pixels_from_paths(actual)!=ink or runs!=original:
                    raise AssertionError('Attachment order or drawn geometry changed.')
                cases+=1
    for count in (0,1,2,12,40,90,180):
        components=components_fixture(count)
        original=copy.deepcopy(components)
        for calibration in ({},{'samples':5,'ratio':2.1,'operation_runtime':{
                'short_stroke':{'average_seconds':.23},'long_stroke':{'average_seconds':.61}}}):
            for sx,sy in ((1,1),(.6,1.3),(2.1,3.0)):
                model=costs.ExecutionCostModel(dict(_execution_cost_calibration_override=calibration,
                    _execution_scale_x=sx,_execution_scale_y=sy),(240,200),(240,200))
                expected=before_schedule(components,3,cost_model=model)
                actual=strokes.schedule_components(components,3,cost_model=model)
                if actual!=expected or components!=original:
                    raise AssertionError('Complete scheduler result changed.')
                cases+=1
    return cases


def comb_source(size):
    image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image)
    for x in range(8,size[0]-8,3):
        draw.line((x,8,x,size[1]-9),fill=(0,80,205),width=1)
    draw.line((8,size[1]-9,size[0]-9,size[1]-9),fill=(0,80,205),width=1)
    return image


def tile_source(size):
    image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image)
    for y in range(5,size[1]-8,12):
        for x in range(5,size[0]-8,14):
            draw.rectangle((x,y,x+6,y+6),fill=((0,80,205),(239,19,11),(0,0,0))[(x//14+y//12)%3])
    return image


def public_options():
    return opts(render_preset='Manual',time_budget_mode='Unlimited',unlimited_time=True,
        skip_white=True,detail_zoom='Off',cpu_workers_resolved=1,cpu_workers='1',
        _execution_cost_calibration_override={},ram_budget_mb=2048,
        available_ram_mb=8192,logical_cpus=4,resource_scheduler='Off')


def independent_plan_raster(plan):
    with closing(Image.new('RGB',plan['image'].size,'white')) as raster:
        draw=ImageDraw.Draw(raster)
        for entry in plan['execution_sequence']:
            path=entry['path'];color=tuple(plan['colors'][entry['color_index']])
            if len(path)==1:draw.point(path[0],fill=color)
            elif path:draw.line(path,fill=color,width=1)
        np.testing.assert_array_equal(np.asarray(raster),np.asarray(plan['options']['_accuracy_quantized_target']))


def source_hashes():
    return {path.name:hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))
            if not path.name.startswith(('test_','benchmark_')) or path.name in (
                Path(__file__).name,'benchmark_v148_image_workflow.py','benchmark_v148_stroke_optimizer.py',
                'test_pixel_accurate_v1086.py','test_v148_rendering_batch06_canvas.py',
                'test_v148_rendering_batch14_prepared_cost.py')}


def measure(revision=BASELINE, repeats=6):
    if type(repeats) is not int or repeats<2 or repeats%2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA samples.')
    before_merge,merge_hash=historical_function('_merge_horizontal_runs_lossless',revision)
    before_schedule,schedule_hash=historical_function('schedule_components',revision)
    after_merge=strokes._merge_horizontal_runs_lossless
    after_schedule=strokes.schedule_components
    sources=source_hashes()
    result={'baseline':revision,'python':sys.version.split()[0],'platform':platform.platform(),
        'numpy':np.__version__,'pillow':pillow_version,'repeats':repeats,
        'baseline_function_sha256':{'_merge_horizontal_runs_lossless':merge_hash,'schedule_components':schedule_hash},
        'source_sha256':sources,'complete_parity_cases':parity_cases(before_merge,before_schedule),
        'method':'One warm pair, balanced AB/BA pairs, separate traced allocation peaks after garbage collection; complete outputs compared on every warm, counted, timed and traced call.',
        'isolation':'R1401 replaces only _merge_horizontal_runs_lossless; R1403 replaces only schedule_components. Each historical function imports the current globals, preserving all unrelated product changes on both sides.',
        'timing_scope':'Whole public make_plan including identical complete-result fingerprinting and owned-image cleanup; helper timings include identical output fingerprinting. No native drawing, GPU or GUI benchmark.',
        'memory_scope':'Tracemalloc peaks include Python/NumPy allocations, not RSS or most native Pillow pixel storage.',
        'public_plan_exclusions':['.'.join(path) for path in sorted(VOLATILE_PATHS)],'measurements':{}}

    runs=[(index*3,y,index*3+1,y) for y in range(25) for index in range(180)]
    def merger_call(function):return fingerprint(function(runs))
    def arithmetic_count(function):
        calls=0
        def counted(*args,**kwargs):
            nonlocal calls
            calls+=1
            return builtins.max(*args,**kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(function.__globals__,{'max':counted}))
            # Historical function globals are isolated, while its unchanged
            # attachment helpers still use the current module globals. Count
            # that shared arithmetic on both sides as well.
            if function.__globals__ is not vars(strokes):
                stack.enter_context(patch.dict(vars(strokes),{'max':counted}))
            merger_call(function)
        return calls
    result['measurements']['R1401_parallel_runs_4500']={
        **paired(lambda:merger_call(before_merge),lambda:merger_call(after_merge),repeats),
        'before_max_calls':arithmetic_count(before_merge),'after_max_calls':arithmetic_count(after_merge),
        'parameters':{'rows':25,'runs_per_row':180,'run_length':2,'horizontal_spacing':3}}

    components=components_fixture(180)
    model=costs.ExecutionCostModel({'_execution_cost_calibration_override':{}},(240,200),(240,200))
    def schedule_call(function):return fingerprint(function(components,3,cost_model=model))
    def path_cost_count(operation):
        with patch.object(costs.ExecutionCostModel,'path_cost',autospec=True,side_effect=costs.ExecutionCostModel.path_cost) as counted:
            operation()
            return counted.call_count
    result['measurements']['R1403_scheduler_180_components']={
        **paired(lambda:schedule_call(before_schedule),lambda:schedule_call(after_schedule),repeats),
        'before_path_cost_calls':path_cost_count(lambda:schedule_call(before_schedule)),
        'after_path_cost_calls':path_cost_count(lambda:schedule_call(after_schedule)),
        'parameters':{'components':180,'paths_per_component':1,'points_per_path':18,'palette':3,'phases':4}}

    with patch('DrawTimeCalibration.load_profile',return_value=None):
        for group,name,before,after,fixture,sizes in (
                ('R1401','_merge_horizontal_runs_lossless',before_merge,after_merge,comb_source,((320,112),(480,160))),
                ('R1403','schedule_components',before_schedule,after_schedule,tile_source,((96,72),(192,144)))):
            for size in sizes:
                with closing(fixture(size)) as source:
                    settings=public_options()
                    def public_call(function, prove_ink=False):
                        with patch.object(strokes,name,new=function):
                            plan=DrawBot.make_plan(source,size,dict(settings))
                        try:
                            if prove_ink:independent_plan_raster(plan)
                            return comparable_plan(plan)
                        finally:close_plan(plan,source)
                    expected=public_call(before,True)
                    if public_call(after,True)!=expected:
                        raise AssertionError('Independent public-plan parity failed.')
                    row=paired(lambda:public_call(before),lambda:public_call(after),repeats)
                    if group=='R1403':
                        row.update(before_path_cost_calls=path_cost_count(lambda:public_call(before)),
                                   after_path_cost_calls=path_cost_count(lambda:public_call(after)))
                    result['measurements'][f'{group}_public_make_plan_{size[0]}x{size[1]}']={
                        **row,'parameters':{'size':size,'fixture':fixture.__name__,'options':settings},
                        'paths':expected['count'],'component_count':expected['options']['pixel_stroke_meta']['component_count'],
                        'independent_native_grid_ink_parity':True}
    if source_hashes()!=sources:
        raise AssertionError('Root Python sources changed during benchmark; rerun after coordination.')
    result['source_unchanged_during_measurement']=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE)
    parser.add_argument('--repeats',type=int,default=6)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch14-rendering-benchmarks.json')
    args=parser.parse_args();result=measure(args.baseline,args.repeats)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:{name:value[name] for name in ('before_median_ms','after_median_ms','exact_output_parity')}
        for key,value in result['measurements'].items()},indent=2))
