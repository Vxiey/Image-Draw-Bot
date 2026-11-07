"""Paired production state-renderer benchmark with real headless Tcl writes.

This measures Python/state assembly and Python-to-Tcl presentation dispatch,
not CustomTkinter raster redraws, native GUI frame rate or physical input.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time
import tkinter as tk
from types import SimpleNamespace

import StudioUI

BASELINE='f59a57c6fc1eef1ace07e872ba50ed834e1bb924'


class Value:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class Presentation:
    def __init__(self,interpreter,name):
        self.interpreter=interpreter;self.name=name;self.values={};self.calls=0;self.writes=0;self.manager=''
    def configure(self,**values):
        self.calls+=1
        for key,value in values.items():
            self.interpreter.setvar(f'{self.name}_{key}',str(value));self.writes+=1
        self.values.update(values)
    def winfo_manager(self):return self.manager
    def pack(self,**kwargs):self.manager='pack'
    def pack_forget(self):self.manager=''


def renderer(source):
    syntax=ast.parse(source)
    node=next(node for node in ast.walk(syntax) if isinstance(node,ast.FunctionDef) and node.name=='_apply_ui_state')
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    return compile(module,'StudioUI._apply_ui_state','exec')


def fixture(compiled):
    interpreter=tk.Tcl();widgets=[];readiness={}
    def widget():
        item=Presentation(interpreter,f'widget_{len(widgets)}');widgets.append(item);return item
    def read(name):
        readiness[name]=readiness.get(name,0)+1
        return False
    app=SimpleNamespace(closing=False,original=SimpleNamespace(size=(800,600),mode='RGB'),corners=[],activity='draw',
        plan=None,game=Value('Microsoft Paint'),status=Value('Drawing: 0/1000 brush strokes'),setup_wizard_text=Value(''),
        palette_button=widget(),area_button=widget(),app_tool_button=widget(),
        start=SimpleNamespace(cget=lambda key:'disabled'))
    start=Presentation(interpreter,'start_secondary');app.start_secondary=start
    app._safe_widget_configure=lambda target,**values:target.configure(**values)
    for name in ('_paint_tool_preflight_ready','_target_lock_valid','_safety_preflight_valid','_dry_run_valid','_full_draw_unlocked'):
        setattr(app,name,lambda name=name:read(name))
    scope=dict(vars(StudioUI));scope.update(a=app,ui_state_job={'id':None},ui_state_running={'value':False},
        palette_ready_now=lambda:False,gpu_summary=lambda:'CPU',step_headers={3:(widget(),widget())},
        step_dots={n:widget() for n in range(1,6)},checklist_rows={})
    for name in ('top_state','profile_pill','profile_guide_icon','profile_guide_badge','profile_guide_tip',
                 'profile_guide_recommend','image_info','plan_metrics','error_title','error_message','error_action','error_card'):
        scope[name]=widget()
    for key in ('image','target','tools','area','palette','test','lock','preflight','dryrun','gpu'):
        scope['checklist_rows'][key]=(None,widget(),widget())
    exec(compiled,scope)
    return app,scope['_apply_ui_state'],widgets,start,readiness


def sample(compiled,iterations):
    app,update,widgets,start,readiness=fixture(compiled)
    then=time.perf_counter()
    for number in range(iterations):
        app.status.set(f'Drawing: {number}/1000 brush strokes');update()
    seconds=time.perf_counter()-then
    final={'widgets':[widget.values for widget in widgets],'start':start.values,
           'wizard':app.setup_wizard_text.get(),'readiness':readiness}
    return {'seconds':seconds,'presentation_configure_calls':sum(widget.calls for widget in widgets),
        'presentation_tcl_writes':sum(widget.writes for widget in widgets),
        'controller_start_updates':start.calls,'readiness_calls':readiness,
        'visible_result_sha256':hashlib.sha256(json.dumps(final,sort_keys=True).encode()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE)
    parser.add_argument('--samples',type=int,default=7)
    parser.add_argument('--iterations',type=int,default=1000)
    parser.add_argument('--output',type=Path,default=Path('docs/v148-batch06-ui-calibration-benchmarks.json'))
    args=parser.parse_args()
    if not 3<=args.samples<=50 or not 10<=args.iterations<=10000:parser.error('Use 3–50 samples and 10–10,000 iterations.')
    before_source=subprocess.run(['git','show',f'{args.baseline}:StudioUI.py'],check=True,capture_output=True,text=True).stdout
    after_source=Path('StudioUI.py').read_text(encoding='utf-8')
    before=renderer(before_source);after=renderer(after_source)
    sample(before,10);sample(after,10)
    rows={'before':[],'after':[]}
    for index in range(args.samples):
        order=(('before',before),('after',after))
        if index%2:order=tuple(reversed(order))
        for name,compiled in order:rows[name].append(sample(compiled,args.iterations))
    if len({row['visible_result_sha256'] for side in rows.values() for row in side})!=1:
        raise AssertionError('Before/after presentation or controller state changed.')
    report={'baseline_commit':args.baseline,'python':platform.python_version(),'platform':platform.platform(),
        'scope':'Actual production renderer with deterministic variable/widget adapters and real Tcl setvar writes; no native CTk redraw, GUI frame-rate, hardware/input or GPU claim.',
        'iterations':args.iterations,'samples':args.samples,
        'baseline_source_sha256':hashlib.sha256(before_source.encode()).hexdigest(),
        'current_source_sha256':hashlib.sha256(Path('StudioUI.py').read_bytes()).hexdigest(),**rows,
        'before_median_seconds':statistics.median(row['seconds'] for row in rows['before']),
        'after_median_seconds':statistics.median(row['seconds'] for row in rows['after'])}
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:report[name] for name in ('before_median_seconds','after_median_seconds')},indent=2))
    print(json.dumps({name:{key:value for key,value in side[0].items() if key!='seconds'} for name,side in rows.items()},indent=2))


if __name__=='__main__':main()
