"""Deterministic old-vs-Adaptive-Hybrid benchmark for Image Draw Bot v1.0.132-beta.

This suite measures Python planning time and the calibrated input-time model on
six synthetic fixtures. It deliberately does NOT report estimated input time as
actual Windows drawing time. `actual_draw_seconds` remains None unless a future
real target harness records it.
"""
from __future__ import annotations

import json
import math
import time
import tracemalloc
from contextlib import closing
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw

from AdaptiveRegionHybrid import (_build_fill_regions, build_adaptive_execution,
                                  pixel_map_from_groups, simulate_quantized_plan)
from ExecutionCostModel import build_cost_model
from FillOptimizer import remove_filled_region_strokes
from PixelAccuratePlanner import build_pixel_map, groups_from_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan

PALETTE = (
    (255,255,255),(18,18,18),(220,42,52),(34,155,92),(45,105,220),
    (245,205,45),(135,135,135),(235,125,32),(145,70,185),(50,185,190),
)


def _icon():
    im=Image.new('RGB',(160,120),'white');d=ImageDraw.Draw(im)
    d.rounded_rectangle((18,18,142,102),radius=20,fill=PALETTE[3],outline=PALETTE[1],width=3)
    d.rectangle((54,43,106,77),fill=PALETTE[5]);d.ellipse((70,51,90,71),fill=PALETTE[2])
    return im


def _line_art():
    im=Image.new('RGB',(160,120),'white');d=ImageDraw.Draw(im)
    d.ellipse((18,16,142,104),outline=PALETTE[1],width=2)
    d.line((30,88,70,38,98,84,132,28),fill=PALETTE[1],width=2)
    d.arc((52,44,108,96),10,165,fill=PALETTE[4],width=2)
    return im


def _text_detail():
    im=Image.new('RGB',(180,120),'white');d=ImageDraw.Draw(im)
    d.rectangle((8,10,171,109),outline=PALETTE[1],width=2)
    # deterministic pseudo-text: thin strokes, dots and small colour accents.
    x=18
    for width in (10,8,12,7,11,9,13,8):
        d.line((x,30,x,49),fill=PALETTE[1],width=1);d.line((x,30,x+width,30),fill=PALETTE[1],width=1)
        d.line((x,40,x+width-2,40),fill=PALETTE[1],width=1);x+=width+6
    for i in range(12):
        xx=20+i*12;d.rectangle((xx,70,xx+2,72),fill=PALETTE[2 if i%3==0 else 4])
    d.line((18,88,160,88),fill=PALETTE[1],width=1)
    return im


def _cartoon():
    im=Image.new('RGB',(180,130),'white');d=ImageDraw.Draw(im)
    d.rectangle((5,76,174,124),fill=PALETTE[9])
    d.ellipse((24,18,118,112),fill=PALETTE[7],outline=PALETTE[1],width=3)
    d.ellipse((48,45,58,55),fill=PALETTE[1]);d.ellipse((84,45,94,55),fill=PALETTE[1])
    d.arc((50,50,94,86),10,170,fill=PALETTE[1],width=2)
    d.polygon(((117,52),(164,75),(119,96)),fill=PALETTE[5],outline=PALETTE[1])
    return im


def _gradient_photo():
    w,h=176,128
    arr=np.zeros((h,w,3),dtype=np.uint8)
    yy,xx=np.mgrid[0:h,0:w]
    arr[...,0]=np.clip(25+xx*1.15+yy*.35,0,255)
    arr[...,1]=np.clip(55+yy*1.35+.22*xx,0,255)
    arr[...,2]=np.clip(190-xx*.55+yy*.30,0,255)
    cx,cy=92,62;r=np.sqrt((xx-cx)**2+(yy-cy)**2)
    arr[r<28]=np.array(PALETTE[7],dtype=np.uint8)
    arr[(r>=28)&(r<31)]=np.array(PALETTE[1],dtype=np.uint8)
    return Image.fromarray(arr,'RGB')


def _fill_risk():
    im=Image.new('RGB',(180,130),'white');d=ImageDraw.Draw(im)
    # donut/hole, narrow-neck shape and adjacent island stress safe Fill.
    d.rectangle((14,14,78,112),fill=PALETTE[3],outline=PALETTE[1],width=2)
    d.rectangle((30,34,62,92),fill='white',outline=PALETTE[1],width=2)
    d.rectangle((98,18,164,48),fill=PALETTE[4],outline=PALETTE[1],width=2)
    d.rectangle((126,48,136,80),fill=PALETTE[4])
    d.rectangle((102,80,160,112),fill=PALETTE[4],outline=PALETTE[1],width=2)
    d.rectangle((80,56,92,68),fill=PALETTE[2])
    return im


CASES: tuple[tuple[str,Callable[[],Image.Image]],...] = (
    ('simple_icon',_icon),('line_art',_line_art),('text_small_detail',_text_detail),
    ('cartoon_flat_areas',_cartoon),('photo_like_gradient',_gradient_photo),
    ('fill_risk_holes_passages',_fill_risk),
)


def _options(seconds: float = 45.0) -> dict:
    return {
        'profile_key':'microsoft-paint','profile_name':'Microsoft Paint','paint_profile':True,
        'speed':'Balanced','precision':'High','delay':.003,'brush_px':1,
        'paint_current_color':False,'paint_stroke_delivery':'Auto',
        'fill_tool_available':True,'fill_tool_actions':[('fill',(1,1))],
        'fill_restore_actions':[('pencil',(2,2))], 'fill_engine':'Closed regions v2',
        'fill_aggressiveness':'Balanced','background_fill':'Balanced','use_region_fill_engine':True,
        'time_budget_active':False,'time_budget_mode':'Unlimited','max_seconds':seconds,
        'manual_max_seconds':seconds,'adaptive_color_verification':False,
        'visual_verification_enabled':False,'cpu_workers_resolved':2,'gpu_mode':'CPU',
        'browser_brush_plan':None,
    }


def _add_cost(a,b):
    return float(a.total_seconds)+float(b.total_seconds)


def _measure(operation, cancelled):
    if cancelled():raise InterruptedError()
    owns_trace=not tracemalloc.is_tracing()
    if owns_trace:tracemalloc.start()
    started=time.perf_counter()
    try:
        value=operation()
        elapsed=(time.perf_counter()-started)*1000.0
        peak=tracemalloc.get_traced_memory()[1] if owns_trace else None
        if cancelled():raise InterruptedError()
        return value,elapsed,peak
    finally:
        if owns_trace:tracemalloc.stop()


def _run_case(name: str, image: Image.Image, *, cancelled=lambda:False) -> dict:
    options=_options();fitted=image.size
    pm,common_ms,_=_measure(lambda:build_pixel_map(image,PALETTE,skip_white=True,gpu_mode='CPU'),cancelled)
    def baseline_pipeline():
        baseline=build_pixel_stroke_plan(pm,len(PALETTE),cpu_workers=2,cancelled=cancelled)
        sequence=[dict(raw,brush_px=1) for raw in baseline['execution_sequence']]
        quality,_=simulate_quantized_plan(pm,sequence,())
        return sequence,quality
    (baseline_seq,base_quality),baseline_plan_ms,baseline_peak=_measure(baseline_pipeline,cancelled)
    model=build_cost_model(options,image.size,fitted)
    base_runtime=model.sequence_cost(baseline_seq)
    base_fixed=model.fixed_overhead(active_colors=len({e['color_index'] for e in baseline_seq}))
    def adaptive_pipeline():
        source_groups=groups_from_pixel_map(pm,len(PALETTE),lines=True,cancelled=cancelled)
        fill_regions,fill_meta=_build_fill_regions(source_groups,PALETTE,image.size,fitted,options,cancelled)
        if cancelled():raise InterruptedError()
        work=remove_filled_region_strokes(source_groups,fill_regions) if fill_regions else source_groups
        work_pm=pixel_map_from_groups(image,work,PALETTE,gpu_mode=options.get('gpu_mode','CPU'),cancelled=cancelled)
        adaptive=build_adaptive_execution(work_pm,PALETTE,options,fitted,fill_regions=fill_regions,
                                          reference_pixel_map=pm,cancelled=cancelled)
        return adaptive,fill_regions,fill_meta
    (adaptive,fill_regions,fill_meta),adaptive_plan_ms,adaptive_peak=_measure(adaptive_pipeline,cancelled)
    adaptive_runtime=model.sequence_cost(adaptive['execution_sequence'])
    adaptive_fixed=model.fixed_overhead(active_colors=len({e['color_index'] for e in adaptive['execution_sequence']}),
                                        fill_actions=len(fill_regions))
    adaptive_est=_add_cost(adaptive_runtime,adaptive_fixed)
    baseline_est=_add_cost(base_runtime,base_fixed)
    return {
        'case':name,'canvas':list(image.size),
        'baseline':{
            'engine':'Pixel Stroke Engine Block B','planning_ms':round(baseline_plan_ms,3),
            'estimated_draw_seconds':round(baseline_est,4),'actual_draw_seconds':None,
            'operations':len(baseline_seq),'palette_switches':base_runtime.palette_switches,
            'brush_switches':base_runtime.brush_switches,'fill_actions':0,
            'python_peak_kib':None if baseline_peak is None else round(baseline_peak/1024,1),'quality':base_quality,
        },
        'adaptive':{
            'engine':'Adaptive Region Hybrid 4.0','planning_ms':round(adaptive_plan_ms,3),
            'estimated_draw_seconds':round(adaptive_est,4),'actual_draw_seconds':None,
            'operations':len(adaptive['execution_sequence'])+len(fill_regions),
            'palette_switches':adaptive_runtime.palette_switches,'brush_switches':adaptive_runtime.brush_switches,
            'fill_actions':len(fill_regions),'python_peak_kib':None if adaptive_peak is None else round(adaptive_peak/1024,1),
            'quality':adaptive['metrics'],'methods':adaptive['metadata'].get('methods',{}),
            'fill_safety':(fill_meta.get('stateful_fill_simulation') or {}),
        },
        'comparison':{
            'estimated_draw_delta_seconds':round(adaptive_est-baseline_est,4),
            'planning_delta_ms':round(adaptive_plan_ms-baseline_plan_ms,3),
            'quality_score_delta':round(float(adaptive['metrics']['pixel_accuracy_score'])-float(base_quality['pixel_accuracy_score']),4),
        },
        'measurement':{
            'planning_time':'measured locally with perf_counter in this process',
            'planning_scope':'each engine includes its own preparation, path construction and quality simulation; common quantization is reported separately',
            'common_preparation_ms':round(common_ms,3),
            'memory':'isolated Python trace per measured stage; unavailable when caller tracing is already active',
            'draw_time':'calibrated/modelled only; not real Windows mouse execution',
            'real_windows_input_verified':False,'real_gpu_execution_verified':False,
        },
    }


def run_benchmarks(*, cancelled=lambda:False) -> dict:
    rows=[]
    for name,factory in CASES:
        if cancelled():raise InterruptedError()
        with closing(factory()) as image:
            rows.append(_run_case(name,image,cancelled=cancelled))
    if cancelled():raise InterruptedError()
    return {
        'schema':1,'suite':'Image Draw Bot Adaptive Hybrid deterministic benchmark',
        'cases':rows,'case_count':len(rows),'palette_colors':len(PALETTE),
        'actual_windows_input_measured':False,'gpu_backend':'CPU/NumPy deterministic benchmark',
        'notes':['Estimated draw seconds are not actual measured target-app times.',
                 'Quality metrics are produced by the same discrete plan simulator for both engines.'],
    }


def format_summary(result: dict) -> str:
    lines=['case | old plan ms | new plan ms | old est s | new est s | old ops | new ops | new score | fills']
    lines.append('-'*108)
    for row in result['cases']:
        b=row['baseline'];a=row['adaptive']
        lines.append(f"{row['case']:<25} {b['planning_ms']:>10.2f} {a['planning_ms']:>11.2f} "
                     f"{b['estimated_draw_seconds']:>9.2f} {a['estimated_draw_seconds']:>9.2f} "
                     f"{b['operations']:>8} {a['operations']:>8} "
                     f"{a['quality']['pixel_accuracy_score']:>9.2f} {a['fill_actions']:>5}")
    return '\n'.join(lines)


if __name__=='__main__':
    result=run_benchmarks();print(format_summary(result));print('BENCHMARK_JSON='+json.dumps(result,sort_keys=True))

