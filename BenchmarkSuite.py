"""Deterministic local benchmark suite for Image Draw Bot Step 10.

No mouse, keyboard, screen-capture, network or telemetry APIs are used here.
The caller supplies the normal planning function and receives compact result rows.
"""
from __future__ import annotations

import time
from copy import deepcopy
from contextlib import closing
from typing import Callable, Any
from PIL import Image, ImageDraw
from RuntimePaths import is_finite_number

TARGETS = (75, 80, 150, 300)
TARGET_MODES = ('Gartic Phone Fast', 'Skribbl Default', 'Gartic Phone Normal', 'Gartic Phone Slow')


def _flat() -> Image.Image:
    im=Image.new('RGBA',(320,220),(250,250,250,255));d=ImageDraw.Draw(im)
    d.ellipse((38,42,282,184),fill=(244,207,42,255),outline=(86,61,24,255),width=5)
    d.ellipse((82,86,120,124),fill=(255,247,207,255));d.rectangle((174,92,260,134),fill=(42,145,82,255))
    return im


def _hues() -> Image.Image:
    im=Image.new('RGBA',(320,220),'white');d=ImageDraw.Draw(im)
    colors=((222,45,55),(245,202,35),(42,166,83),(46,101,218))
    for i,c in enumerate(colors):
        x=10+i*78;d.rounded_rectangle((x,22,x+68,198),radius=18,fill=c)
        d.ellipse((x+18,72,x+50,104),fill=(250,250,250))
    return im


def _texture() -> Image.Image:
    im=Image.new('RGBA',(320,220),'white');px=im.load()
    for y in range(220):
        for x in range(320):
            band=(x//16+y//11)%5
            r=max(0,min(255,120+x//3-band*8));g=max(0,min(255,70+y//2+band*10));b=max(0,min(255,52+(x+y)//7))
            px[x,y]=(r,g,b,255)
    d=ImageDraw.Draw(im);d.ellipse((95,48,235,188),outline=(20,25,30,255),width=4)
    return im


def _detail() -> Image.Image:
    im=Image.new('RGBA',(320,220),'white');d=ImageDraw.Draw(im)
    d.rectangle((24,20,296,200),outline=(22,22,22,255),width=4)
    for y in range(36,194,13): d.line((35,y,285,y),fill=(65,65,65,255),width=1)
    for x in range(42,286,19): d.line((x,30,x,190),fill=(115,115,115,255),width=1)
    d.ellipse((112,66,208,162),fill=(235,85,72,255),outline=(25,25,25,255),width=3)
    d.ellipse((139,95,153,109),fill=(10,10,10,255));d.ellipse((169,95,183,109),fill=(10,10,10,255))
    d.arc((138,112,184,145),0,180,fill=(10,10,10,255),width=2)
    return im


CASES=(('flat-illustration',_flat),('dominant-hues',_hues),('texture',_texture),('small-detail',_detail))


def _number(value, *, maximum=None):
    if not is_finite_number(value) or value<0 or (maximum is not None and value>maximum):return None
    return float(value)


def run(make_plan: Callable[..., dict], base_options: dict, *, cancelled=lambda:False,
        target_area=(480,320)) -> dict[str, Any]:
    rows=[];suite_started=time.monotonic()
    for index,(name,factory) in enumerate(CASES):
        if cancelled(): raise InterruptedError()
        seconds=TARGETS[index]; mode=TARGET_MODES[index]
        options=deepcopy(base_options)
        options.update({'time_budget_active':True,'time_budget_seconds':seconds,'max_seconds':seconds,
                        'manual_max_seconds':seconds,'time_budget_mode':mode,'_preview_plan':True,
                        '_preview_mode':'Benchmark suite','planning_resolution':'Standard'})
        with closing(factory()) as image:
            started=time.monotonic();plan=make_plan(image,target_area,options,cancelled);elapsed=time.monotonic()-started
        if cancelled():raise InterruptedError()
        acc=(plan.get('options') or {}).get('adaptive_accuracy_meta') or {}
        de=(plan.get('options') or {}).get('preview_delta_e_meta') or {}
        timing=plan.get('draw_time_estimate') or {}
        projected=_number(timing.get('projected_seconds'))
        if projected is None:projected=_number(plan.get('estimate'))
        plan_options=plan.get('options') or {}
        usable=_number(plan_options.get('deadline_render_budget_seconds',seconds))
        acceptance=plan_options.get('auto_tuner_acceptance_meta') or {}
        rows.append({
            'case':name,'target_seconds':seconds,'usable_seconds':None if usable is None else round(usable,3),
            'planning_seconds':round(elapsed,4),'source_strokes':int(plan.get('source_count',0) or 0),
            'planned_paths':int(plan.get('count',0) or 0),'estimated_draw_seconds':None if projected is None else round(projected,3),
            'fits_budget':projected is not None and usable is not None and usable>0 and projected<=usable,
            'visual_accuracy_percent':_number(acc.get('visual_accuracy_percent'),maximum=100),
            'perceptual_color_accuracy_percent':_number(acc.get('perceptual_color_accuracy_percent'),maximum=100),
            'mean_delta_e_oklab':_number(de.get('mean_delta_e_oklab')),'p95_delta_e_oklab':_number(de.get('p95_delta_e_oklab')),
            'palette_colors':len(plan.get('colors') or ()),
            'auto_tuner_status':acceptance.get('status'),
            'acceptance_passed':acceptance.get('accepted') if type(acceptance.get('accepted')) is bool else None,
            'visual_gate_percent':(acceptance.get('gates') or {}).get('visual_accuracy_min_percent'),
            'auto_tuner_strategy':(plan_options.get('auto_tuner_meta') or {}).get('selected_strategy'),
        })
    if cancelled():raise InterruptedError()
    total=time.monotonic()-suite_started
    fit=sum(1 for row in rows if row['fits_budget'])
    accepted=sum(1 for row in rows if row.get('acceptance_passed') is True)
    acceptance_available=any(row.get('acceptance_passed') is not None for row in rows)
    visual=[float(r['visual_accuracy_percent']) for r in rows if r.get('visual_accuracy_percent') is not None]
    return {'version':2,'local_only':True,'mouse_input':False,'rows':rows,'total_seconds':round(total,4),
            'fit_count':fit,'acceptance_pass_count':accepted if acceptance_available else None,
            'case_count':len(rows),'average_visual_accuracy_percent':round(sum(visual)/len(visual),2) if visual else None}


def format_result(result: dict[str,Any]) -> str:
    rows=result.get('rows') or []
    parts=[]
    for row in rows:
        accuracy=row.get('visual_accuracy_percent')
        a='n/a' if accuracy is None else f'{float(accuracy):.1f}%'
        fit='UNKNOWN' if row.get('estimated_draw_seconds') is None or row.get('usable_seconds') is None else 'FIT' if row.get('fits_budget') else 'OVER'
        gate=''
        if row.get('acceptance_passed') is not None:
            gate=' · gate PASS' if row.get('acceptance_passed') else f" · gate {row.get('auto_tuner_status') or 'FAIL'}"
        estimate='n/a' if row.get('estimated_draw_seconds') is None else f"{float(row['estimated_draw_seconds']):.1f}s"
        usable='n/a' if row.get('usable_seconds') is None else f"{float(row['usable_seconds']):.0f}s"
        parts.append(f"{row.get('case')} {fit} {estimate}/{usable} · visual {a}{gate} · plan {float(row.get('planning_seconds',0)):.2f}s")
    avg=result.get('average_visual_accuracy_percent')
    header=f"Benchmark suite: {int(result.get('fit_count',0))}/{int(result.get('case_count',0))} within usable budgets"
    if result.get('acceptance_pass_count') is not None:
        header+=f" · {int(result.get('acceptance_pass_count',0))}/{int(result.get('case_count',0))} pass Step 11 gates"
    if avg is not None: header+=f" · avg visual {float(avg):.1f}%"
    return header + ('\n' + '\n'.join(parts) if parts else '')
