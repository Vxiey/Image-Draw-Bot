"""Paired CPU benchmark of inactive runtime suffix replanning, not mouse speed."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import types

import DeadlineScheduler as current

BASELINE='5f3fcfb5c4519e5ed1b9b770ba951918819d725d'
ROOT=Path(__file__).resolve().parent


def baseline_module():
    source=subprocess.check_output(['git','show',BASELINE+':DeadlineScheduler.py'],cwd=ROOT).decode()
    module=types.ModuleType('_v148_runtime_baseline');sys.modules[module.__name__]=module
    exec(compile(source,BASELINE+':DeadlineScheduler.py','exec'),module.__dict__)
    return module,source


def workload(module,kind,*,updated,paths=20000,steps=200):
    entries=[{'color_index':i%4,'path':((i,0),(i,1)), 'brush_px':1,
              'phase':'structure','operation_type':'stroke','estimated_cost_seconds':.01,
              'importance':.9,'structural_score':.9} for i in range(paths)]
    scheduler=module.DeadlineScheduler(entries,start_time=0,budget_seconds=None if kind=='unlimited' else 1000,clock=lambda:0)
    scheduler.mode=module.CATCH_UP if kind=='throttled' else module.NORMAL
    scheduler._global_samples=10;scheduler._last_replan_sample=9
    scheduler._last_replan_mode=scheduler.mode
    def run():
        for index in range(steps):
            if updated:
                scheduler.replan_in_place(entries,index+1)
            else:
                remaining=list(entries[index+1:])
                reordered=scheduler.replan_remaining(remaining)
                if reordered!=remaining:entries[index+1:]=reordered
    def result():
        digest=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()
        return {'ordered_entries_sha256':digest,'scheduler_metadata':scheduler.meta()}
    return run,result


def measured(run):
    started=time.perf_counter();run();return (time.perf_counter()-started)*1000


def peak(run):
    gc.collect();tracemalloc.start()
    try:run();return tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch05-runtime-benchmarks.json')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    baseline,old_source=baseline_module();rows=[]
    for kind in ('normal','unlimited','throttled'):
        before,before_result=workload(baseline,kind,updated=False)
        after,after_result=workload(current,kind,updated=True)
        before();after();assert before_result()==after_result()
        samples={'before_ms':[],'after_ms':[]}
        for repeat in range(args.repeats):
            order=(('before_ms',before),('after_ms',after))
            for key,run in (order if repeat%2==0 else reversed(order)):
                samples[key].append(measured(run))
        assert before_result()==after_result()
        row={'policy':kind,'paths':20000,'replan_checks':200,'exact_output_parity':True,
             **samples,'before_median_ms':statistics.median(samples['before_ms']),
             'after_median_ms':statistics.median(samples['after_ms']),
             'before_peak_python_bytes':peak(before),'after_peak_python_bytes':peak(after),
             'output':after_result()}
        rows.append(row)
        print(kind,round(row['before_median_ms'],3),'->',round(row['after_median_ms'],3),'ms')
    document={'baseline_commit':BASELINE,'baseline_DeadlineScheduler_sha256':hashlib.sha256(old_source.encode()).hexdigest(),
              'current_sources_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('DeadlineScheduler.py','DrawBot.py')},
              'python':platform.python_version(),'platform':platform.platform(),
              'scope':'Repeated eligibility checks on a prepared runtime sequence. Scheduler construction, mouse/native input, drawing and active sorting are excluded. Baseline follows the original DrawBot tail-copy call pattern. Current shared dependencies are used.',
              'results':rows}
    args.output.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
