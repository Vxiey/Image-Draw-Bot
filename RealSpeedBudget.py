"""Measured browser-throughput budgeting for Image Draw Bot v1.0.77.

The profile is learned locally from completed Image Draw Bot browser executions. It
stores only timing counters (paths, seconds, color batches, profile key), never
screenshots, source images, URLs, account data or telemetry.

The planner uses the learned throughput conservatively for preset time budgets,
reduces color/detail work when needed, and enables structural path priority so
large outlines/forms survive before micro detail.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
from pathlib import Path
from typing import Sequence

from RuntimePaths import atomic_write_text, data_dir, file_transaction, read_json
from AdaptivePaletteFidelity import adaptive_palette_cap, select_adaptive_palette

SPEED_FILE = data_dir() / 'real-speed-profiles.json'
VERSION = 1
MAX_SPEED_FILE_BYTES = 1024 * 1024
SUPPORTED = frozenset({'gartic-phone','skribbl','skribbl-fast','sketchheads','sketchful'})

# Conservative fallback rates used only until a real completed sample exists.
FALLBACK_PPS = {
    'gartic-phone': 5.2,
    'skribbl': 5.5,
    'skribbl-fast': 7.5,
    'sketchheads': 4.7,
    'sketchful': 4.8,
}


def _empty():
    return {'version': VERSION, 'profiles': {}}


def load_all(path: Path = SPEED_FILE) -> dict:
    try:
        raw=read_json(Path(path),max_bytes=MAX_SPEED_FILE_BYTES)
        if (not isinstance(raw,dict) or type(raw.get('version')) is not int
                or raw['version']!=VERSION or not isinstance(raw.get('profiles'),dict)):
            return _empty()
        return {'version':VERSION,'profiles':dict(raw['profiles'])}
    except (OSError,ValueError,TypeError,RecursionError,OverflowError):
        return _empty()


def save_all(data: dict, path: Path = SPEED_FILE) -> None:
    with file_transaction(path):
        atomic_write_text(Path(path),json.dumps({'version':VERSION,'profiles':data.get('profiles') or {}},ensure_ascii=False,indent=2,allow_nan=False))


def load_profile(profile_key: str, path: Path = SPEED_FILE) -> dict | None:
    key=str(profile_key or '').lower()
    item=load_all(path)['profiles'].get(key)
    return _clean_profile(item)


def _clean_profile(item):
    if not isinstance(item, dict):
        return None
    try:
        pps = float(item.get('paths_per_second', 0.0))
        samples = int(item.get('samples', 0))
        total_paths = int(item.get('total_paths', 0))
        total_seconds = float(item.get('total_seconds', 0.0))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(pps) or not .2 <= pps <= 80.0 or samples < 0 or total_paths < 0 or not math.isfinite(total_seconds) or total_seconds < 0:
        return None
    out = dict(item)
    out.update(paths_per_second=pps, samples=samples, total_paths=total_paths, total_seconds=total_seconds)
    return out


def record_runtime_sample(profile_key: str, paths: int, elapsed_seconds: float, *,
                          colors: int = 0, test_run: bool = False, path: Path = SPEED_FILE) -> dict:
    """Update a robust EMA from a clean completed browser execution.

    Tiny samples are ignored. Small-test samples are accepted but deliberately
    weighted less than normal drawings because palette/prelude overhead is a
    larger fraction of those runs.
    """
    key=str(profile_key or '').lower()
    try:
        paths=max(0,int(paths));elapsed=float(elapsed_seconds);colors=max(0,int(colors))
    except (TypeError, ValueError, OverflowError):
        return {'recorded':False,'profile_key':key,'reason':'invalid timing sample'}
    if key not in SUPPORTED or paths < 3 or not math.isfinite(elapsed) or elapsed < .20:
        return {'recorded':False,'profile_key':key,'reason':'sample too small or unsupported'}
    pps=max(.20,min(80.0,paths/elapsed))
    with file_transaction(path):
        return _record_runtime_sample_locked(key, paths, elapsed, colors, test_run, pps, path)


def _record_runtime_sample_locked(key, paths, elapsed, colors, test_run, pps, path):
    db=load_all(path);profiles=db['profiles'];old=_clean_profile(profiles.get(key)) or {}
    old_pps=float(old.get('paths_per_second') or 0.0)
    # More completed paths = more trust. Small test remains useful as a first
    # sample but cannot swing a mature profile sharply.
    size_weight=min(1.0,paths/180.0)
    alpha=(.16+.44*size_weight) * (.45 if test_run else 1.0)
    if old_pps <= 0:
        learned=pps
    else:
        learned=old_pps*(1.0-alpha)+pps*alpha
    samples=int(old.get('samples') or 0)+1
    total_paths=int(old.get('total_paths') or 0)+paths
    total_seconds=float(old.get('total_seconds') or 0.0)+elapsed
    if not math.isfinite(total_seconds):
        return {'recorded':False,'profile_key':key,'reason':'invalid timing total'}
    profile={
        'profile_key':key,
        'paths_per_second':round(learned,5),
        'seconds_per_path':round(1.0/max(.001,learned),6),
        'last_sample_pps':round(pps,5),
        'last_paths':paths,
        'last_seconds':round(elapsed,4),
        'last_colors':max(0,int(colors)),
        'samples':samples,
        'total_paths':total_paths,
        'total_seconds':round(total_seconds,4),
        'last_test_run':bool(test_run),
        'updated_at':time.time(),
    }
    profiles[key]=profile;save_all(db,path)
    result=dict(profile);result['recorded']=True
    return result


def _fallback_from_static_cap(profile_key: str, seconds: int, static_cap: int | None) -> float:
    if static_cap is not None:
        drawable=max(4.0,float(seconds)-8.0)
        inferred=float(static_cap)/drawable
        if .5 <= inferred <= 40:
            return inferred
    return float(FALLBACK_PPS.get(profile_key,5.0))


@dataclass(frozen=True)
class BudgetRecommendation:
    profile_key: str
    seconds: int
    learned: bool
    paths_per_second: float
    path_cap: int
    max_colors: int
    detail_level: str
    structure_priority: bool
    reserve_seconds: float
    safety_factor: float

    def as_dict(self) -> dict:
        return {
            'profile_key':self.profile_key,'seconds':self.seconds,'learned':self.learned,
            'paths_per_second':round(self.paths_per_second,4),'path_cap':self.path_cap,
            'max_colors':self.max_colors,'detail_level':self.detail_level,
            'structure_priority':self.structure_priority,'reserve_seconds':self.reserve_seconds,
            'safety_factor':self.safety_factor,
        }


def recommend_budget(profile_key: str, seconds: int, *, static_cap: int | None = None,
                     color_fidelity: str = 'Fast', path: Path = SPEED_FILE) -> BudgetRecommendation:
    key=str(profile_key or '').lower();seconds=max(5,int(seconds))
    stored=load_profile(key,path) if key in SUPPORTED else None
    learned=bool(stored and int(stored.get('samples') or 0)>0)
    pps=float(stored.get('paths_per_second')) if learned else _fallback_from_static_cap(key,seconds,static_cap)
    # Browser input starts after target activation/countdown/tool setup. Keep a
    # fixed reserve plus a larger safety factor when the profile is not learned.
    reserve=7.0 if seconds <= 90 else 8.0
    drawable=max(3.0,float(seconds)-reserve)
    safety=.82 if learned else .72
    cap=max(40,min(15000,int(drawable*max(.2,pps)*safety)))
    if static_cap is not None and not learned:
        cap=min(cap,max(1,int(static_cap)))

    # v1.0.123: colour switches are cheap relative to thousands of browser
    # strokes. A fixed 4/6/8-colour cap caused severe posterization on rich
    # images, so palette capacity now scales with fidelity + deadline.
    colors=adaptive_palette_cap(seconds,color_fidelity,profile_key=key,paths_per_second=pps)
    if seconds <= 60:
        detail='Strong simplify'
    elif seconds <= 120:
        detail='Balanced'
    else:
        detail='Preserve detail'
    return BudgetRecommendation(key,seconds,learned,pps,cap,colors,detail,True,reserve,safety)


def apply_budget_policy(options: dict, *, path: Path = SPEED_FILE) -> dict:
    """Apply measured-budget hints to a copy of resolved planning options."""
    out=dict(options)
    if not bool(out.get('time_budget_active')) or bool(out.get('preview_plan')):
        return out
    key=str(out.get('profile_key') or '').lower()
    if key not in SUPPORTED:
        return out
    current=out.get('target_stroke_count_resolved')
    try: static_cap=int(current) if current is not None else None
    except (TypeError,ValueError): static_cap=None
    # v1.0.119 TimeBudgetEngine already separates total game time from the
    # usable render budget. Feed the original timer here so Real-Speed's own
    # reserve is not subtracted a second time from an already reduced budget.
    _timer_seconds=int(out.get('deadline_total_seconds') or out.get('time_budget_seconds') or out.get('max_seconds') or 60)
    rec=recommend_budget(key,_timer_seconds,static_cap=static_cap,color_fidelity=str(out.get('color_fidelity') or 'Fast'),path=path)
    # Explicit user caps are respected if lower. Auto gets the measured cap.
    if str(out.get('target_stroke_count') or 'Auto')=='Auto':
        out['target_stroke_count_resolved']=rec.path_cap
        out['target_stroke_count_reason']='real-speed-budget'
    elif static_cap is not None:
        out['target_stroke_count_resolved']=min(static_cap,rec.path_cap)
    out['real_speed_budget_meta']=rec.as_dict()
    out['real_speed_structure_priority']=True
    out['real_speed_max_colors']=rec.max_colors
    if str(out.get('profile_engine') or 'Auto')!='Manual settings':
        out['color_grouping']='Reduced palette'
        if rec.detail_level=='Strong simplify':
            out['adaptive_detail']='Strong simplify'
        if rec.seconds <= 90:
            out['planning_resolution']='Standard'
        if key=='skribbl-fast':
            out['skribbl_fast_max_colors']=rec.max_colors
        if key=='gartic-phone':
            out['gartic_phone_max_colors']=rec.max_colors
    return out


def _segment_weight(stroke) -> float:
    try:
        x1,y1,x2,y2=map(float,stroke)
        return max(1.0,math.hypot(x2-x1,y2-y1))
    except Exception:
        return 1.0


def reduce_palette_groups(groups: Sequence[Sequence[tuple]], palette_rgb: Sequence[Sequence[int]], max_colors: int, *,
                          color_fidelity: str = 'Balanced') -> tuple[list[list[tuple]],dict]:
    """Adaptive perceptual browser-palette reduction.

    v1.0.123 replaces the old "largest N colours + darkest anchor" policy.
    Tone/hue/spatial anchors are preserved and additional colours are selected
    by weighted visual gain per palette-switch cost.
    """
    work=[list(map(tuple,g)) for g in groups]
    max_colors=max(2,int(max_colors))
    rgbs=[tuple(map(int,r[:3])) for r in palette_rgb]
    keep,mapping,quality=select_adaptive_palette(work,rgbs,max_colors,fidelity=str(color_fidelity or 'Balanced'))
    if not keep:
        meta=dict(quality);meta.update({'active':False,'before_colors':0,'after_colors':0,'remapped_colors':0,'mapping':{}})
        return work,meta
    active=[i for i,g in enumerate(work) if g and i<len(rgbs)]
    if len(active)<=len(keep) and all(mapping.get(i,i)==i for i in active):
        meta=dict(quality);meta.update({'active':False,'before_colors':len(active),'after_colors':len(active),'remapped_colors':0,'mapping':{str(i):i for i in active}})
        return work,meta
    result=[[] for _ in work];remapped=0
    for i in active:
        target=int(mapping.get(i,i))
        if target!=i:remapped+=1
        result[target].extend(work[i])
    meta=dict(quality)
    meta.update({
        'active':True,'before_colors':len(active),'after_colors':sum(bool(g) for g in result),
        'remapped_colors':remapped,'max_colors':max_colors,
        'kept_color_indexes':tuple(map(int,keep)),
        'mapping':{str(i):int(mapping.get(i,i)) for i in active},
        'anti_posterization':True,'color_fidelity':str(color_fidelity or 'Balanced'),
    })
    return result,meta
