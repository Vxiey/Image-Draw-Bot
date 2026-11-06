"""Paired, read-only CPU measurements against a chosen git checkpoint.

No native input or screen capture is used. Run from the repository root:
python benchmark_v148_runtime.py --output docs/v148-batch02-runtime-benchmarks.json
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import statistics
import subprocess
import time
import types

import numpy as np
from PIL import Image

import AutoDrawing
import GarticTimer
from UICompactLayout import CompactGroup


def baseline_module(ref,name):
    source=subprocess.check_output(['git','show',f'{ref}:{name}.py'],text=True,encoding='utf-8')
    module=types.ModuleType(f'baseline_{name}')
    exec(compile(source,f'{ref}:{name}.py','exec'),module.__dict__)
    return module


def paired(before,after,repeats=7):
    expected=before();actual=after()
    if actual!=expected:raise AssertionError('Optimized output differs from baseline.')
    timings=[[],[]]
    for number in range(repeats):
        for index in ((0,1) if number%2==0 else (1,0)):
            started=time.perf_counter()
            value=(before,after)[index]()
            timings[index].append((time.perf_counter()-started)*1000)
            if value!=expected:raise AssertionError('Benchmark output changed between runs.')
    return {'output_equal':True,'repeats':repeats,
            'before_median_ms':statistics.median(timings[0]),
            'after_median_ms':statistics.median(timings[1]),
            'before_samples_ms':timings[0],'after_samples_ms':timings[1]}


def pack_calls(group_class):
    from test_v148_ui_lifecycle_batch02 import PackedWidget
    parent=types.SimpleNamespace(order=[])
    parent.pack_slaves=lambda:list(parent.order)
    group=object.__new__(group_class)
    group.parent=parent;group.open=True;group.shell=object();group.saved_pack={}
    group.layout=types.SimpleNamespace(scope_by_widget={})
    group.items=[PackedWidget(parent) for _ in range(100)]
    parent.order=[group.shell]+group.items
    for _ in range(100):group.refresh()
    if parent.order!=[group.shell]+group.items:raise AssertionError('Incorrect final widget order.')
    return sum(w.packs+w.unpacks for w in group.items)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',default='1c09774ad22088c5c30a8f8220b6b451fdee9659')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    old_auto=baseline_module(args.baseline,'AutoDrawing')
    old_timer=baseline_module(args.baseline,'GarticTimer')
    old_layout=baseline_module(args.baseline,'UICompactLayout')
    results={}
    rng=np.random.default_rng(148)
    for mode,channels in (('RGB',3),('RGBA',4)):
        with Image.fromarray(rng.integers(0,256,(2000,3000,channels),dtype=np.uint8)) as source:
            results[f'preset_analysis_{mode}_3000x2000']=paired(
                lambda:old_auto.resolve_drawing(source,{'render_preset':'Masterpiece'}),
                lambda:AutoDrawing.resolve_drawing(source,{'render_preset':'Masterpiece'}))
    import test_gartic_timer_v10101 as fixtures
    with Image.new('RGB',(3200,2000),(158,25,82)) as frame,fixtures.TimerTests().frame(.5) as ring:
        frame.paste(ring,(0,0))
        results['timer_ring_81x81_in_3200x2000']=paired(
            lambda:old_timer.read_ring(frame,(200,30,281,111)),
            lambda:GarticTimer.read_ring(frame,(200,30,281,111)))
    results['unchanged_sidebar_100_controls_100_refreshes']={
        'same_final_order':True,'before_pack_mutations':pack_calls(old_layout.CompactGroup),
        'after_pack_mutations':pack_calls(CompactGroup)}
    report={'baseline':args.baseline,'measured_at_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Linux CPU helper measurements; excludes Windows capture/input, native widget rendering and full drawing time.',
            'measurements':results}
    text=json.dumps(report,indent=2,allow_nan=False)+'\n'
    if args.output:args.output.write_text(text,encoding='utf-8')
    print(text,end='')


if __name__=='__main__':main()
