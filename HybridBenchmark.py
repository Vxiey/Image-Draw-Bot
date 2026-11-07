"""Deterministic six-case old/new hybrid planner benchmark.

This benchmark is local-only. It measures planning wall time and plan/simulation
metrics. `actual_draw_seconds` remains None unless a caller supplies a real
verified Windows executor measurement.
"""
from __future__ import annotations
import time,tracemalloc
from copy import deepcopy
from contextlib import closing
from typing import Any,Callable
from PIL import Image,ImageDraw
from RuntimePaths import is_finite_number


def _icon():
    im=Image.new('RGBA',(240,180),'white');d=ImageDraw.Draw(im);d.rounded_rectangle((30,28,210,152),24,fill='#e8bc32',outline='#202020',width=5);d.ellipse((70,65,95,90),fill='black');return im

def _line():
    im=Image.new('RGBA',(240,180),'white');d=ImageDraw.Draw(im);d.ellipse((32,22,208,158),outline='black',width=3);d.line((60,118,120,55,180,118),fill='black',width=2);return im

def _text_detail():
    im=Image.new('RGBA',(240,180),'white');d=ImageDraw.Draw(im);d.rectangle((14,14,226,166),outline='black',width=3);d.text((25,25),'DRAW 123',fill='black');
    for x in range(28,212,13):d.line((x,75,x,145),fill=(70,70,70),width=1)
    d.ellipse((105,102,111,108),fill='red');return im

def _cartoon():
    im=Image.new('RGBA',(240,180),(210,235,255,255));d=ImageDraw.Draw(im);d.ellipse((45,22,195,166),fill=(255,204,64),outline='black',width=4);d.ellipse((82,68,102,88),fill='black');d.rectangle((115,98,175,130),fill=(54,160,92),outline='black',width=3);return im

def _photo():
    im=Image.new('RGBA',(240,180),'white');p=im.load()
    for y in range(180):
        for x in range(240):p[x,y]=(int(30+210*x/239),int(40+180*y/179),int(185-120*x/239+40*y/179),255)
    ImageDraw.Draw(im).ellipse((68,35,175,152),outline=(20,20,20),width=3);return im

def _fill_risk():
    im=Image.new('RGBA',(240,180),'white');d=ImageDraw.Draw(im);d.rectangle((24,20,216,160),fill=(70,145,225),outline='black',width=3);d.rectangle((72,55,168,125),fill='white',outline='black',width=2);d.rectangle((118,20,122,92),fill='white');d.line((25,144,215,144),fill='red',width=1);return im

CASES=(('icon',_icon),('line-art',_line),('text-small-detail',_text_detail),('cartoon-large-colour',_cartoon),('photo-gradient',_photo),('fill-risk',_fill_risk))


def _row(make_plan,image,area,base_options,enabled,cancelled):
    if cancelled():raise InterruptedError()
    options=deepcopy(base_options);options['adaptive_hybrid_cost']='Auto' if enabled else 'Off';options['_preview_plan']=True
    owns_trace=not tracemalloc.is_tracing()
    if owns_trace:tracemalloc.start()
    start=time.perf_counter()
    try:
        with closing(image.copy()) as planner_image:
            plan=make_plan(planner_image,area,options,cancelled)
        elapsed=time.perf_counter()-start
        peak=tracemalloc.get_traced_memory()[1] if owns_trace else None
        if cancelled():raise InterruptedError()
    finally:
        if owns_trace:tracemalloc.stop()
    po=plan.get('options') or {};acc=po.get('adaptive_accuracy_meta') or {};de=po.get('preview_delta_e_meta') or {};timing=plan.get('draw_time_estimate') or {}
    seq=plan.get('execution_sequence') or []
    switches=sum(1 for a,b in zip(seq,seq[1:]) if a.get('color_index')!=b.get('color_index'))
    fills=len(po.get('fill_regions') or ())+(1 if (po.get('background_fill_plan') or {}).get('enabled') else 0)
    estimate=next((float(v) for v in (timing.get('projected_seconds'),plan.get('estimate')) if is_finite_number(v) and v>=0),None)
    return {'engine':'calibrated-hybrid' if enabled else 'legacy-fallback','planning_seconds':round(elapsed,5),'estimated_draw_seconds':None if estimate is None else round(estimate,4),'actual_draw_seconds':None,'operations':int(plan.get('count') or 0),'color_switches':switches,'fill_actions':fills,'peak_python_memory_bytes':peak,'memory_measurement':'isolated Python trace' if owns_trace else 'unavailable: caller tracing is active','visual_accuracy_percent':acc.get('visual_accuracy_percent'),'coverage_percent':acc.get('coverage_percent'),'spill_percent':acc.get('spill_percent'),'perceptual_color_accuracy_percent':acc.get('perceptual_color_accuracy_percent'),'mean_delta_e_oklab':de.get('mean_delta_e_oklab'),'performance_profile':plan.get('performance_profile') or {},'gpu_backend':(po.get('universal_gpu_meta') or po.get('gpu_meta') or {}).get('backend')}


def run(make_plan:Callable[...,dict],base_options:dict[str,Any],*,area=(480,360),cancelled=lambda:False):
    rows=[]
    for name,factory in CASES:
        if cancelled():raise InterruptedError()
        with closing(factory()) as image:
            legacy=_row(make_plan,image,area,base_options,False,cancelled)
            hybrid=_row(make_plan,image,area,base_options,True,cancelled)
        delta=None if hybrid['estimated_draw_seconds'] is None or legacy['estimated_draw_seconds'] is None else round(hybrid['estimated_draw_seconds']-legacy['estimated_draw_seconds'],4)
        rows.append({'case':name,'legacy':legacy,'hybrid':hybrid,'estimated_draw_delta_seconds':delta,'operation_delta':hybrid['operations']-legacy['operations']})
    if cancelled():raise InterruptedError()
    return {'version':1,'local_only':True,'real_windows_input_verified':False,'actual_draw_times_measured':False,'cases':rows,'case_count':len(rows),'note':'Planning/simulation comparison only. Actual Windows input time and physical GPU execution must be measured on a real configured target.'}
