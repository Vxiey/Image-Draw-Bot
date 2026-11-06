"""Bounded representative dry-run planning for Image Draw Bot v1.0.46.

Pure helpers only: no native input. Dry run validates representative canvas/color
routes instead of replaying every final stroke.
"""
from __future__ import annotations

from collections.abc import Sequence

DRY_RUN_PLANNING_SECONDS = 8.0
DRY_RUN_EXECUTION_SECONDS = 12.0
DRY_RUN_MAX_COLORS = 4
DRY_RUN_MAX_PATHS = 8

class DryRunBudgetComplete(InterruptedError):
    """Expected soft stop when the bounded dry-run cursor budget is exhausted."""


def sample_indices(length, limit):
    length=max(0,int(length));limit=max(0,int(limit))
    if not length or not limit:return []
    if length<=limit:return list(range(length))
    if limit==1:return [0]
    values=[]
    for i in range(limit):
        idx=round(i*(length-1)/(limit-1))
        if idx not in values:values.append(idx)
    return values


def sample_items(items, limit):
    seq = items if isinstance(items, Sequence) else list(items or ())
    return [seq[i] for i in sample_indices(len(seq),limit)]


def _active_order(plan):
    groups=plan.get('groups') or []
    execution=plan.get('execution_groups')
    order=(plan.get('options') or {}).get('color_order') or list(range(len(groups)))
    active = []
    seen = set()
    for value in order:
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if index in seen or not 0 <= index < len(groups):
            continue
        seen.add(index)
        if groups[index] or (execution is not None and index < len(execution) and execution[index]):
            active.append(index)
    return active


def sample_plan(plan, *, max_colors=DRY_RUN_MAX_COLORS, max_paths=DRY_RUN_MAX_PATHS,
                execution_seconds=DRY_RUN_EXECUTION_SECONDS):
    """Return a shallow safe dry-run plan capped to representative routes."""
    max_colors = max(0, int(max_colors))
    max_paths = max(0, int(max_paths))
    out=dict(plan); options=dict(plan.get('options') or {})
    options.update({
        'max_seconds':float(execution_seconds),
        'manual_max_seconds':float(execution_seconds),
        'time_budget_seconds':float(execution_seconds),
        'visual_verification_enabled':False,
        'adaptive_color_verification':False,
        'strict_color_verification':False,
        'background_fill_plan':None,
        'fill_regions':[],
        'dry_run_sampled':True,
    })
    out['options']=options
    sequence=plan.get('execution_sequence') or ()
    if not isinstance(sequence, Sequence):
        sequence = list(sequence)
    if sequence:
        active_colors = list(dict.fromkeys(entry.get('color_index') for entry in sequence
                                          if entry.get('color_index') is not None))
        chosen = [active_colors[index] for index in sample_indices(len(active_colors), min(max_colors, max_paths))]
        selected = set(chosen)
        eligible = [entry for entry in sequence if entry.get('color_index') is None or entry.get('color_index') in selected]
        sampled = sample_items(eligible, max_paths) if max_colors and max_paths else []
        out['execution_sequence']=sampled
        out['count']=len(sampled)
        options['color_order'] = list(dict.fromkeys(entry.get('color_index') for entry in sampled
                                                   if entry.get('color_index') is not None))
        options['dry_run_total_colors'] = len(active_colors)
        options['dry_run_sample_colors'] = len(options['color_order'])
        options['dry_run_total_paths']=len(sequence)
        options['dry_run_sample_paths']=len(sampled)
        return out

    groups=plan.get('groups') or []
    exec_groups=plan.get('execution_groups')
    active=_active_order(plan)
    chosen=[active[i] for i in sample_indices(len(active),min(max_colors, max_paths))]
    options['color_order']=chosen
    per_color=max(1,int(max_paths)//max(1,len(chosen)))
    new_groups=[[] for _ in groups]
    new_exec=None if exec_groups is None else [[] for _ in groups]
    count=0
    for index in chosen:
        if exec_groups is not None and index<len(exec_groups) and exec_groups[index]:
            picked=sample_items(exec_groups[index],per_color)
            new_exec[index]=picked;new_groups[index]=list(groups[index])
            count+=len(picked)
        else:
            picked=sample_items(groups[index],per_color)
            new_groups[index]=picked;count+=len(picked)
    out['groups']=new_groups;out['execution_groups']=new_exec;out['count']=count
    options['dry_run_total_colors']=len(active)
    options['dry_run_sample_colors']=len(chosen)
    options['dry_run_total_paths']=int(plan.get('count') or 0)
    options['dry_run_sample_paths']=count
    return out
