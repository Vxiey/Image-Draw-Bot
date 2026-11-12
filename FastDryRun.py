"""Bounded representative dry-run planning for Image Draw Bot v1.0.46.

Pure helpers only: no native input. Dry run validates representative canvas/color
routes instead of replaying every final stroke.
"""
from __future__ import annotations

from collections.abc import Sequence
from RenderResume import execution_sequence_with_brushes

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
                execution_seconds=DRY_RUN_EXECUTION_SECONDS, cancelled=lambda: False):
    """Return a shallow safe dry-run plan capped to representative routes."""
    if cancelled():
        raise InterruptedError('Dry-run preparation cancelled.')
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
        collected = []
        for number, entry in enumerate(sequence):
            if number % 256 == 0 and cancelled():
                raise InterruptedError('Dry-run preparation cancelled.')
            collected.append(entry)
        sequence = collected
    if sequence:
        prepared_plan = dict(plan, execution_sequence=sequence)
        color_counts = {}
        # Use the executor's own definition of a drawable sequence operation.
        # Empty/colorless/invalid rows are not brush commands and cannot supply
        # a width to a later sampled path.
        for entry in execution_sequence_with_brushes(prepared_plan, cancelled=cancelled):
            color = entry['color_index']
            color_counts[color] = color_counts.get(color, 0) + 1
        active_colors = list(color_counts)
        chosen = [active_colors[index] for index in sample_indices(len(active_colors), min(max_colors, max_paths))]
        selected = set(chosen)
        eligible_count = sum(color_counts[color] for color in selected)
        selected_ordinals = set(sample_indices(eligible_count, max_paths))
        sampled = []
        ordinal = 0
        # A retained entry can inherit its width from a discarded color or path.
        # Resolve state through the original order, then detach only the bounded
        # sample. Repeated references to the same entry may have different
        # inherited widths at their different occurrences.
        for entry in execution_sequence_with_brushes(prepared_plan, cancelled=cancelled):
            if entry['color_index'] in selected:
                if ordinal in selected_ordinals:
                    sampled.append(dict(entry))
                ordinal += 1
        out['execution_sequence']=sampled
        out['count']=len(sampled)
        if not sampled:
            # The executor's legacy fallback reads groups when no sequence is
            # present. An intentionally empty sample must not revive full work.
            out['groups']=[[] for _ in (plan.get('groups') or ())]
            if plan.get('execution_groups') is not None:
                out['execution_groups']=[[] for _ in plan['execution_groups']]
        options['color_order'] = list(dict.fromkeys(entry.get('color_index') for entry in sampled
                                                   if entry.get('color_index') is not None))
        options['dry_run_total_colors'] = len(active_colors)
        options['dry_run_sample_colors'] = len(options['color_order'])
        options['dry_run_total_paths']=sum(color_counts.values())
        options['dry_run_sample_paths']=len(sampled)
        if cancelled():
            raise InterruptedError('Dry-run preparation cancelled.')
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
        if cancelled():
            raise InterruptedError('Dry-run preparation cancelled.')
        if exec_groups is not None and index<len(exec_groups) and exec_groups[index]:
            picked=sample_items(exec_groups[index],per_color)
            new_exec[index]=picked;new_groups[index]=groups[index]
            count+=len(picked)
        else:
            picked=sample_items(groups[index],per_color)
            new_groups[index]=picked;count+=len(picked)
    out['groups']=new_groups;out['execution_groups']=new_exec;out['count']=count
    options['dry_run_total_colors']=len(active)
    options['dry_run_sample_colors']=len(chosen)
    options['dry_run_total_paths']=int(plan.get('count') or 0)
    options['dry_run_sample_paths']=count
    if cancelled():
        raise InterruptedError('Dry-run preparation cancelled.')
    return out
