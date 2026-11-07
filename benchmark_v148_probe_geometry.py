"""Paired geometry-probe allocation benchmark plus actual fake-device execution."""
import argparse
import ast
from contextlib import ExitStack
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import threading
import time
import tracemalloc
from unittest.mock import patch

from PIL import Image

import DrawBot
from StrokeProbeGeometry import representative_segment
from test_drawbot import Mouse, NoWait
from test_visual_verification_v1043 import simple_visual_plan

ROOT = Path(__file__).resolve().parent
BASELINE = '4c8aa247f852df7225b5e7d10ce4ac151e612226'


def old_choice(subpaths, reads):
    # The exact list construction / max policy in the baseline draw_path_item.
    points = [p for path in subpaths for p in path]
    pairs = [(a,b) for path in subpaths for a,b in zip(path,path[1:]) if a != b]
    start,end = subpaths[0][0],subpaths[-1][-1]
    chosen = max(pairs,key=lambda p:(p[1][0]-p[0][0])**2+(p[1][1]-p[0][1])**2) if pairs else (start,end)
    if reads > 1 and len(points) > 2 and pairs:
        chosen = max(pairs,key=lambda p:(p[1][0]-p[0][0])**2+(p[1][1]-p[0][1])**2)
    if reads > 2 and pairs:
        chosen = max(pairs,key=lambda p:(p[1][0]-p[0][0])**2+(p[1][1]-p[0][1])**2)
    return chosen


def measure(run):
    started=time.perf_counter(); result=run()
    return (time.perf_counter()-started)*1000,result


def peak(run):
    gc.collect();tracemalloc.start()
    try:run();return tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()


def paired(before, after, repeats):
    assert before() == after()
    samples={'before_ms':[],'after_ms':[]}
    for repeat in range(repeats):
        order=(('before_ms',before),('after_ms',after))
        for key,fn in (order if repeat%2==0 else reversed(order)):
            elapsed,result=measure(fn);samples[key].append(elapsed)
    assert before() == after()
    return {**samples,'before_median_ms':statistics.median(samples['before_ms']),
            'after_median_ms':statistics.median(samples['after_ms']),
            'before_peak_python_bytes':peak(before),'after_peak_python_bytes':peak(after),
            'exact_output_parity':True}


def legacy_executor():
    source=subprocess.check_output(['git','show',BASELINE+':DrawBot.py'],cwd=ROOT).decode()
    tree=ast.parse(source)
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute_plan')
    namespace=dict(vars(DrawBot))
    exec(compile(ast.Module(body=[function],type_ignores=[]),BASELINE+':execute_plan','exec'),namespace)
    return namespace['execute_plan'],source


def execution_workload(execute):
    class CheckedMouse(Mouse):
        def __init__(self):super().__init__();self.probes=[]
        def verify_ink_segment(self,*args):self.probes.append(args)
    plan=simple_visual_plan();plan['image'].close()
    plan['image']=Image.new('RGB',(96,96),'white');plan['fitted']=(96,96)
    paths=[tuple((6+(i%80),6+((i//80+j*3)%80)) for i in range(640)) for j in range(8)]
    plan['groups']=[paths,[]];plan['count']=len(paths)
    plan['execution_sequence']=[{'color_index':0,'path':p,'brush_px':2,'phase':'major_coverage',
                                  'estimated_cost_seconds':.01,'importance':1.,'structural_score':1.} for p in paths]
    plan['options'].update(visual_verification='Off',visual_verification_resolved='Off',
                           visual_verification_enabled=False,strict_color_verification=True,
                           unlimited_time=True,edge_behavior='Hard Clip')
    mouse=CheckedMouse()
    try:
        execute(plan,(100,100,96,96),[(10,10),(20,10)],mouse,NoWait(),threading.Event(),
                lambda *args:None,clock=lambda:0)
        return mouse.actions,mouse.probes
    finally:plan['image'].close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch06-probe-benchmarks.json')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    legacy,source=legacy_executor();rows=[]
    for name,subpaths,loops,reads in (
            ('two-point strokes',(((0,0),(30,10)),),10000,1),
            ('long compound stroke / one probe',tuple(tuple((i,j) for i in range(2500)) for j in range(4)),10,1),
            ('long compound stroke / three probe consumers',tuple(tuple((i,j) for i in range(2500)) for j in range(4)),10,3)):
        def before():
            for _ in range(loops):result=old_choice(subpaths,reads)
            return result
        def after():
            for _ in range(loops):result=representative_segment(subpaths)
            return result
        row={'case':name,'iterations':loops,'points_per_iteration':sum(map(len,subpaths)),
             **paired(before,after,args.repeats)}
        rows.append(row)
    with ExitStack() as stack:
        stack.enter_context(patch('DrawBot.log_event'))
        stack.enter_context(patch('DrawBot.save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
        # Legacy function copied DrawBot's globals before patching; replace the
        # two I/O sinks too. Its execution body remains the baseline AST.
        legacy.__globals__['log_event']=DrawBot.log_event
        legacy.__globals__['save_runtime_safety_report']=DrawBot.save_runtime_safety_report
        for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            stack.enter_context(patch(name,return_value={}))
        before=lambda:execution_workload(legacy)
        after=lambda:execution_workload(DrawBot.execute_plan)
        native=paired(before,after,args.repeats)
        actions,probes=after()
        rows.append({'case':'actual execute_plan / fake device / 8 compound paths',**native,
                     'native_action_count':len(actions),'ink_probe_count':len(probes),
                     'native_actions_sha256':hashlib.sha256(json.dumps(actions).encode()).hexdigest()})
    document={'baseline_commit':BASELINE,'baseline_DrawBot_sha256':hashlib.sha256(source.encode()).hexdigest(),
              'current_sources_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                        for name in ('DrawBot.py','StrokeProbeGeometry.py')},
              'python':platform.python_version(),'platform':platform.platform(),
              'scope':'First three cases isolate scratch allocation and geometry selection. The last executes baseline/current execute_plan with current shared dependencies, a no-wait fake mouse and disabled persistence. It compares every mouse action and ink probe; it does not measure Windows painting, screen capture or real wall-clock drawing speed. Intentionally changed isolated-dot behavior is tested separately.',
              'results':rows}
    args.output.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
    for row in rows:
        print(row['case'],round(row['before_median_ms'],3),'->',round(row['after_median_ms'],3),'ms;',
              row['before_peak_python_bytes'],'->',row['after_peak_python_bytes'],'peak Python bytes')


if __name__=='__main__':main()
