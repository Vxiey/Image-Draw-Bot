"""Step 11 — end-to-end quality/speed auto tuner and acceptance gates.

The tuner composes the truthful source-relative metrics (Step 1), OKLab colour
pipeline (Steps 2-6), Extra Fast 2.0 (Step 7), runtime deadline scheduler
(Step 8), profile-isolated calibration (Step 9) and preview diagnostics
(Step 10).  It is deterministic and local-only: no ML, network, screen capture,
mouse input or OCR.

Only the Auto render preset opts in. Manual, Masterpiece and explicit Extra Fast
remain authoritative. The first pass selects a bounded renderer/detail/speed/
colour-ceiling policy from image complexity, target profile and usable deadline.
After planning, source-relative accuracy and the measured-calibrated draw-time
projection are checked against centralized acceptance gates. One bounded rescue
replan may be requested when the first plan clearly misses the deadline or has
spare time but misses the visual gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
from PIL import Image

from AdaptiveColorCount import recommend_adaptive_color_count
from SpeedOptimizer import base_delay


AUTO_TUNER_VERSION = 2
ACCEPTANCE_TOLERANCE_PERCENT = 0.10  # avoid gate flapping from sub-tenth-percent metric jitter

# Centralized acceptance policy. Values are intentionally attainable under game
# deadlines while becoming stricter as more time is available.
_GATE_TIERS = (
    # usable seconds, Visual, perceptual colour, edges, coverage
    # Visual Accuracy is the primary acceptance floor. The component floors are
    # deliberately lower so a recognisable game drawing is not rejected only
    # because one diagnostic (often edge similarity with a wide brush) is lower.
    (82.0, 70.0, 64.0, 58.0, 90.0),
    (155.0, 74.0, 68.0, 62.0, 92.0),
    (305.0, 78.0, 72.0, 66.0, 94.0),
    (float('inf'), 86.0, 80.0, 72.0, 96.0),
)


@dataclass(frozen=True)
class SourceFeatures:
    complexity: float
    entropy: float
    edge_density: float
    white_fraction: float
    chromatic_fraction: float
    tone_bins: int
    dominant_hues: tuple[str, ...]
    step5_recommended: int
    significant_colors: int
    source_kind: str
    sample_size: tuple[int, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            'complexity': round(self.complexity, 4),
            'color_entropy': round(self.entropy, 4),
            'edge_density': round(self.edge_density, 4),
            'white_fraction': round(self.white_fraction, 4),
            'chromatic_fraction': round(self.chromatic_fraction, 4),
            'tone_bins': int(self.tone_bins),
            'dominant_hues': tuple(self.dominant_hues),
            'step5_recommended_colors': int(self.step5_recommended),
            'significant_colors': int(self.significant_colors),
            'source_kind': self.source_kind,
            'sample_size': tuple(map(int, self.sample_size)),
        }


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return v if math.isfinite(v) else float(default)


def _bounded_stats(image: Image.Image, max_side: int = 128) -> tuple[float, float]:
    w, h = image.size
    rgb = image
    if max(w, h) > max_side:
        scale = float(max_side) / float(max(w, h))
        size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        # RGB and greyscale resampling commutes with conversion. Avoid a full
        # source-size RGB copy for the common RGB screenshot/photo input.
        if image.mode in ('RGB', 'L'):
            rgb = image.resize(size, Image.Resampling.BOX)
        else:
            with image.convert('RGB') as converted:
                rgb = converted.resize(size, Image.Resampling.BOX)
    owned = rgb is not image
    if rgb.mode != 'RGB':
        converted = rgb.convert('RGB')
        if owned:
            rgb.close()
        rgb = converted
        owned = True
    a = np.asarray(rgb, dtype=np.int16)
    if owned:
        rgb.close()
    if not a.size:
        return 1.0, 0.0
    white = float(np.mean(np.min(a, axis=2) >= 238))
    chroma = a.max(axis=2) - a.min(axis=2)
    chromatic = float(np.mean(chroma >= 30))
    return white, chromatic


def _classify_source(white: float, chromatic: float, meta: dict[str, Any], hint: str | None) -> str:
    if hint in ('line art', 'flat illustration', 'photo / texture'):
        return str(hint)
    complexity = _finite(meta.get('complexity_score'), .5)
    entropy = _finite(meta.get('color_entropy'), .5)
    significant = int(_finite(meta.get('significant_color_buckets'), 8))
    if white >= .64 and chromatic <= .14:
        return 'line art'
    if significant <= 8 and complexity <= .42 and entropy <= .72:
        return 'flat illustration'
    return 'photo / texture'


def analyze_source(image: Image.Image, *, fidelity: str = 'Faithful', source_kind_hint: str | None = None,
                   cancelled=lambda: False) -> SourceFeatures:
    """Build a bounded deterministic source-complexity probe.

    Step 5 remains the authoritative adaptive-colour analyser; Step 11 reuses it
    rather than introducing a second incompatible complexity metric.
    """
    if cancelled():
        raise InterruptedError()
    count, meta = recommend_adaptive_color_count(image, ceiling=32, fidelity=fidelity,
                                                 preview=True, cancelled=cancelled)
    if cancelled():
        raise InterruptedError()
    white, chromatic = _bounded_stats(image)
    if cancelled():
        raise InterruptedError()
    source_kind = _classify_source(white, chromatic, meta, source_kind_hint)
    return SourceFeatures(
        complexity=max(0.0, min(1.0, _finite(meta.get('complexity_score'), .5))),
        entropy=max(0.0, min(1.0, _finite(meta.get('color_entropy'), .5))),
        edge_density=max(0.0, min(1.0, _finite(meta.get('edge_density'), .2))),
        white_fraction=white,
        chromatic_fraction=chromatic,
        tone_bins=max(1, int(_finite(meta.get('tone_bins'), 1))),
        dominant_hues=tuple(meta.get('dominant_hue_families') or ()),
        step5_recommended=max(2, int(count)),
        significant_colors=max(2, int(_finite(meta.get('significant_color_buckets'), count))),
        source_kind=source_kind,
        sample_size=tuple(meta.get('sample_size') or image.size),
    )


def _usable_budget(options: dict[str, Any]) -> tuple[bool, float | None, str]:
    mode = str(options.get('time_budget_mode') or 'Manual')
    if bool(options.get('unlimited_time')) or mode in ('Unlimited', 'Unlimited / Accuracy'):
        return False, None, 'unlimited'
    if bool(options.get('time_budget_active')) and options.get('deadline_render_budget_seconds') is not None:
        seconds = _finite(options.get('deadline_render_budget_seconds'), 0.0)
        if seconds > 0:
            return True, seconds, 'resolved deadline'
    # Direct/test calls may provide a named budget without pre-resolving it.
    try:
        from TimeBudgetEngine import resolve_budget
        b = resolve_budget(mode, options.get('manual_max_seconds', options.get('max_seconds', 180)),
                           options.get('deadline_safety_reserve', 'Auto'))
        if b.get('active') and b.get('render_budget_seconds') is not None:
            return True, max(1.0, _finite(b.get('render_budget_seconds'), 1.0)), str(b.get('source') or mode)
    except Exception:
        pass
    return False, None, 'no active deadline'


def _profile_group(options: dict[str, Any]) -> str:
    key = str(options.get('profile_key') or '').strip().lower()
    name = str(options.get('profile_name') or '').strip().lower()
    if key == 'microsoft-paint' or name == 'microsoft paint':
        return 'paint'
    if 'skribbl' in key or 'skribbl' in name:
        return 'skribbl-fast' if 'fast' in key or 'fast' in name else 'browser'
    if 'gartic' in key or 'gartic' in name:
        return 'browser'
    return 'generic'


def _protected_color_floor(features: SourceFeatures) -> int:
    # Step 3/4 protections are non-negotiable: one anchor per dominant hue plus
    # enough room for light/mid/dark structure when present.
    tone = 2 if features.tone_bins >= 3 else 1
    return max(4, min(16, len(features.dominant_hues) + tone + 2))


def _color_ceiling(features: SourceFeatures, profile: str, budget: float | None) -> int:
    floor = _protected_color_floor(features)
    desired = max(floor, min(32, max(features.step5_recommended, int(round(6 + features.complexity * 20)))))
    if budget is None:
        cap = 32
        desired = max(16, desired)
    elif budget <= 82:
        cap = 10 if profile == 'paint' else 14
    elif budget <= 155:
        cap = 16 if profile == 'paint' else 20
    elif budget <= 305:
        cap = 24
    else:
        cap = 32
    if profile == 'skribbl-fast':
        cap = min(cap, 10 if budget is not None and budget <= 82 else 14)
    return max(floor, min(32, cap, max(floor, desired)))


def _strategy(features: SourceFeatures, profile: str, budget: float | None, fill_available: bool) -> dict[str, Any]:
    """Choose renderer/detail/speed knobs before expensive planning."""
    timed = budget is not None
    short = timed and budget <= 82
    medium = timed and budget <= 155
    longish = timed and budget <= 305
    texture = features.source_kind == 'photo / texture'
    flat = features.source_kind == 'flat illustration'

    if short:
        # Step 25: short rounds benefit most from a completed recognisable sketch.
        # Select Quick Sketch only when Fill is actually calibrated/available and
        # the source is not a texture-heavy photo. Safety remains governed by the
        # existing Region Fill Engine + Safe Fill Mask at plan/runtime.
        quick_candidate = bool(fill_available) and (
            features.source_kind in ('line art', 'flat illustration') or
            (features.complexity <= .62 and features.significant_colors <= 12 and features.edge_density <= .42)
        )
        if quick_candidate:
            simple = features.complexity <= .34 and features.edge_density <= .24
            return {
                'name': 'quick-sketch-fill-contour',
                'render_style': 'Quick Sketch Fill + Contour',
                'quick_sketch_auto': True,
                'quick_sketch_style': 'Simple' if simple else 'Balanced',
                'quick_sketch_fill_preference': 'Safe Fill First',
                'drawing_mode': 'Smart paths (recommended)', 'smart_paths': True, 'lines': True,
                'draw_quality': 'High likeness', 'planning_resolution': 'Standard',
                'quality': 'Balanced', 'detail': 8, 'adaptive_detail': 'Balanced',
                'detail_zoom': 'Auto',
                'speed': 'Fast', 'precision': 'Normal', 'extra_fast': True, 'extra_fast_v2': True,
                'progressive_rendering': 'On', 'stroke_optimizer': 'Smart merge',
                'background_simplification': 'Strong' if simple else 'Balanced',
                'background_fill': 'Off', 'shape_order': 'Fill first',
                'fill_engine': 'Closed regions v2',
                'reason': '75/80-second class budget with fill-safe shape source: complete silhouettes and large fills first, then spend remaining time on critical detail.',
            }
        detail_mode = 'Strong simplify' if texture and features.complexity >= .45 else 'Balanced'
        quality = 'Balanced' if texture and features.complexity >= .58 else 'High likeness'
        return {
            'name': 'deadline-hybrid-fast',
            'drawing_mode': 'Smart paths (recommended)', 'smart_paths': True, 'lines': True,
            'draw_quality': quality, 'planning_resolution': 'Standard',
            'quality': 'Balanced', 'detail': 8, 'adaptive_detail': detail_mode,
            'speed': 'Fast', 'precision': 'Normal', 'extra_fast': True, 'extra_fast_v2': True,
            'progressive_rendering': 'On', 'stroke_optimizer': 'Smart merge',
            'background_simplification': 'Strong' if texture else 'Balanced',
            'background_fill': 'Balanced' if fill_available else 'Off',
            'shape_order': 'Fill first', 'fill_engine': 'Closed regions v2',
            'reason': '75/80-second class budget: maximize safe coverage and recognizable structure first.',
        }
    if medium:
        if flat and features.complexity < .48:
            return {
                'name': 'shape-balanced', 'drawing_mode': 'Shape paths', 'smart_paths': False, 'lines': True,
                'draw_quality': 'High likeness', 'planning_resolution': 'High', 'quality': 'High detail', 'detail': 9,
                'adaptive_detail': 'Preserve detail', 'speed': 'Fast', 'precision': 'High',
                'extra_fast': False, 'extra_fast_v2': False, 'progressive_rendering': 'On',
                'stroke_optimizer': 'Smart merge', 'background_simplification': 'Conservative',
                'background_fill': 'Balanced' if fill_available else 'Off', 'shape_order': 'Fill first',
                'fill_engine': 'Closed regions v2',
                'reason': '150-second class budget with flat regions: use shape quality while preserving deadline headroom.',
            }
        return {
            'name': 'hybrid-balanced', 'drawing_mode': 'Smart paths (recommended)', 'smart_paths': True, 'lines': True,
            'draw_quality': 'High likeness', 'planning_resolution': 'Standard' if texture else 'High',
            'quality': 'High detail', 'detail': 9, 'adaptive_detail': 'Balanced' if texture else 'Preserve detail',
            'speed': 'Fast', 'precision': 'High', 'extra_fast': True, 'extra_fast_v2': True,
            'progressive_rendering': 'On', 'stroke_optimizer': 'Smart merge',
            'background_simplification': 'Balanced', 'background_fill': 'Balanced' if fill_available else 'Off',
            'shape_order': 'Fill first', 'fill_engine': 'Closed regions v2',
            'reason': '150-second class budget: retain important detail but keep the connected-region speed path available.',
        }
    if longish:
        return {
            'name': 'quality-balanced',
            'drawing_mode': 'Smart paths (recommended)' if texture else 'Shape paths',
            'smart_paths': bool(texture), 'lines': True,
            'draw_quality': 'High likeness' if texture else 'Maximum likeness', 'planning_resolution': 'High',
            'quality': 'Maximum detail' if flat else 'High detail', 'detail': 10 if flat else 9,
            'adaptive_detail': 'Preserve detail', 'speed': 'Balanced', 'precision': 'High',
            'extra_fast': bool(texture), 'extra_fast_v2': bool(texture), 'progressive_rendering': 'On',
            'stroke_optimizer': 'Smart merge', 'background_simplification': 'Conservative',
            'background_fill': 'Balanced' if fill_available else 'Off', 'shape_order': 'Fill first',
            'fill_engine': 'Closed regions v2',
            'reason': '300-second class budget: spend added time on detail and likeness while keeping costly texture bounded.',
        }

    # No active deadline. Preserve Auto's historical renderer choices but turn
    # quality up. Masterpiece remains the explicit unconditional Pixel Accurate
    # preset; Auto only selects Pixel Accurate for bounded/simple sources.
    if flat:
        return {
            'name': 'auto-quality-shapes', 'drawing_mode': 'Shape paths', 'smart_paths': False, 'lines': True,
            'draw_quality': 'Maximum likeness', 'planning_resolution': 'High', 'quality': 'Maximum detail', 'detail': 10,
            'adaptive_detail': 'Preserve detail', 'speed': 'Balanced', 'precision': 'High',
            'extra_fast': False, 'extra_fast_v2': False, 'progressive_rendering': 'On',
            'stroke_optimizer': 'Smart merge', 'background_simplification': 'Conservative',
            'background_fill': 'Balanced' if fill_available else 'Off', 'shape_order': 'Fill first',
            'fill_engine': 'Closed regions v2',
            'reason': 'No active deadline and simple flat source: prioritize high-fidelity shape rendering.',
        }
    return {
        'name': 'auto-quality-smart', 'drawing_mode': 'Smart paths (recommended)', 'smart_paths': True, 'lines': True,
        'draw_quality': 'Maximum likeness', 'planning_resolution': 'High', 'quality': 'Maximum detail', 'detail': 10,
        'adaptive_detail': 'Preserve detail', 'speed': 'Balanced', 'precision': 'High',
        'extra_fast': bool(texture), 'extra_fast_v2': bool(texture), 'progressive_rendering': 'On',
        'stroke_optimizer': 'Smart merge', 'background_simplification': 'Conservative',
        'background_fill': 'Balanced' if fill_available else 'Off', 'shape_order': 'Fill first',
        'fill_engine': 'Closed regions v2',
        'reason': 'No active deadline: maximize source likeness while retaining safe optimization for texture-heavy sources.',
    }


def acceptance_gates(options: dict[str, Any], *, features: SourceFeatures | None = None) -> dict[str, Any]:
    active, budget, _ = _usable_budget(options)
    tier_seconds = budget if active and budget is not None else float('inf')
    for limit, visual, perceptual, edge, coverage in _GATE_TIERS:
        if tier_seconds <= limit:
            break
    profile = _profile_group(options)
    profile_delta = 4.0 if profile == 'paint' else (-3.0 if profile == 'skribbl-fast' else 0.0)
    kind_delta = 0.0
    if features is not None and tier_seconds > 82.0:
        if features.source_kind in ('line art', 'flat illustration'):
            kind_delta = 2.0
        elif features.source_kind == 'photo / texture':
            kind_delta = -2.0
    visual = max(60.0, min(96.0, visual + profile_delta + kind_delta))
    perceptual = max(58.0, min(95.0, perceptual + profile_delta + kind_delta))
    edge = max(60.0, min(96.0, edge + (2.0 if profile == 'paint' else 0.0) + kind_delta))
    return {
        'visual_accuracy_min_percent': round(visual, 2),
        'perceptual_color_min_percent': round(perceptual, 2),
        'edge_accuracy_min_percent': round(edge, 2),
        'coverage_min_percent': round(coverage, 2),
        'plan_execution_min_percent': 97.0,
        'deadline_required': bool(active),
        'usable_deadline_seconds': None if budget is None else round(float(budget), 3),
        'policy': 'step11-centralized-v1',
    }


def tune_options(image: Image.Image, options: dict[str, Any], *, source_kind_hint: str | None = None,
                 cancelled=lambda: False) -> dict[str, Any]:
    """Apply Step 11 policy to the Auto preset only."""
    out = dict(options)
    if str(out.get('render_preset') or 'Manual') != 'Auto':
        return out
    if out.get('_auto_tuner_resolved'):
        return out
    if out.get('erase_mode') or out.get('paint_current_color') or out.get('outline'):
        return out

    features = analyze_source(image, fidelity=str(out.get('color_fidelity') or 'Faithful'),
                              source_kind_hint=source_kind_hint, cancelled=cancelled)
    active, budget, budget_source = _usable_budget(out)
    profile = _profile_group(out)
    strategy = _strategy(features, profile, budget if active else None, bool(out.get('fill_tool_available')))
    ceiling = _color_ceiling(features, profile, budget if active else None)

    # Apply only renderer/planning fields. Safety, calibration, target geometry,
    # tool coordinates, arming, locks and native-input controls are untouched.
    for key, value in strategy.items():
        if key not in ('name', 'reason'):
            out[key] = value

    # Step 12: completed real drawings can make one bounded deterministic
    # adjustment to this profile/context. The feedback store contains counters
    # and metrics only; it never persists source/canvas pixels.
    provisional_gates = acceptance_gates(out, features=features)
    feedback = {'active': False, 'state': 'unavailable', 'action': 'none', 'samples': 0}
    try:
        from AutoTunerFeedback import recommend_adjustment
        feedback = recommend_adjustment(
            out, source_kind=features.source_kind, strategy=strategy['name'],
            budget_seconds=budget if active else None, color_ceiling=int(ceiling),
            visual_gate_percent=provisional_gates.get('visual_accuracy_min_percent'))
        if isinstance(feedback, dict):
            for key, value in (feedback.get('changes') or {}).items():
                out[key] = value
            ceiling = int(feedback.get('color_ceiling_after', ceiling) or ceiling)
    except Exception:
        feedback = {'active': False, 'state': 'unavailable', 'action': 'none', 'samples': 0}

    out['mode'] = out.get('drawing_mode')
    out['delay'] = base_delay(str(out.get('speed') or 'Balanced'))
    out['exact_color_limit'] = 'Auto'
    out['exact_color_limit_profile_ceiling'] = int(ceiling)
    out['_auto_tuner_color_ceiling'] = int(ceiling)
    out['_auto_tuner_resolved'] = True
    out['auto_engine_resolved'] = True
    gates = acceptance_gates(out, features=features)
    selected_strategy = strategy['name']
    if isinstance(feedback, dict) and feedback.get('active') and feedback.get('action') not in (None, '', 'none'):
        selected_strategy = f"{strategy['name']}+feedback-{feedback.get('action')}"
    out['auto_tuner_meta'] = {
        'version': AUTO_TUNER_VERSION, 'active': True, 'policy': 'end-to-end-quality-speed-v2-feedback',
        'profile_group': profile, 'base_strategy': strategy['name'], 'selected_strategy': selected_strategy,
        'strategy_reason': strategy['reason'] + (f" Step 12: {feedback.get('reason')}" if feedback.get('active') else ''),
        'source_features': features.as_dict(),
        'time_budget_active': bool(active), 'usable_budget_seconds': budget,
        'budget_source': budget_source, 'color_ceiling': int(ceiling),
        'renderer': out.get('drawing_mode'), 'render_style': out.get('render_style'),
        'quick_sketch': bool(out.get('quick_sketch_auto') or str(out.get('render_style') or '') == 'Quick Sketch Fill + Contour'),
        'quick_sketch_style': out.get('quick_sketch_style'),
        'draw_quality': out.get('draw_quality'),
        'adaptive_detail': out.get('adaptive_detail'), 'detail_zoom': out.get('detail_zoom'), 'planning_resolution': out.get('planning_resolution'),
        'speed_strategy': out.get('speed'), 'extra_fast_2': bool(out.get('extra_fast_v2')),
        'acceptance_gates': gates, 'replan_attempt': int(out.get('_auto_tuner_replan_attempt', 0) or 0),
        'feedback_learning': feedback,
    }
    return out


def _metric(meta: dict[str, Any], key: str) -> float | None:
    value = meta.get(key)
    if type(value) not in (int, float):
        return None
    v = _finite(value, float('nan'))
    return v if math.isfinite(v) and 0 <= v <= 100 else None


def evaluate_plan_acceptance(plan: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the completed plan against truthful Step 1/10 metrics."""
    options = plan.get('options') or {}
    tuner = options.get('auto_tuner_meta') if isinstance(options, dict) else None
    tuner = tuner if isinstance(tuner, dict) else {}
    features_meta = tuner.get('source_features') if isinstance(tuner.get('source_features'), dict) else {}
    # Gates were fixed before planning so a rescue attempt cannot silently lower
    # the quality bar merely because it chose a faster renderer.
    gates = dict(tuner.get('acceptance_gates') or acceptance_gates(options))
    accuracy = options.get('adaptive_accuracy_meta') or {}
    draw_time = plan.get('draw_time_estimate') or {}
    visual = _metric(accuracy, 'visual_accuracy_percent')
    perceptual = _metric(accuracy, 'perceptual_color_accuracy_percent')
    edge = _metric(accuracy, 'edge_accuracy_percent')
    coverage = _metric(accuracy, 'coverage_percent')
    plan_exec = _metric(accuracy, 'plan_execution_accuracy_percent')
    raw_projected = draw_time.get('projected_seconds', plan.get('estimate'))
    projected = _finite(raw_projected, float('nan'))
    projected = projected if math.isfinite(projected) and projected >= 0 else None
    usable = gates.get('usable_deadline_seconds')
    usable_f = _finite(usable, float('nan'))
    usable_f = usable_f if math.isfinite(usable_f) and usable_f > 0 else None
    def passes(value, gate):
        threshold = _metric(gates, gate)
        return None if value is None or threshold is None else value + ACCEPTANCE_TOLERANCE_PERCENT >= threshold

    checks: dict[str, bool | None] = {
        'visual': passes(visual, 'visual_accuracy_min_percent'),
        'perceptual_color': passes(perceptual, 'perceptual_color_min_percent'),
        'edge': passes(edge, 'edge_accuracy_min_percent'),
        'coverage': passes(coverage, 'coverage_min_percent'),
        'plan_execution': passes(plan_exec, 'plan_execution_min_percent'),
        'deadline': True if not gates.get('deadline_required') else (projected <= usable_f if usable_f is not None and projected is not None else None),
    }
    if 'deadline_required' in gates and type(gates['deadline_required']) is not bool:
        checks['deadline'] = None
    # Step 11 acceptance is intentionally driven by the combined source-relative
    # Visual Accuracy from Step 1. Perceptual/edge/coverage components remain
    # visible diagnostics and must not be double-counted as separate hard gates,
    # because Visual Accuracy already includes them. Plan Execution is likewise a
    # renderer-correctness diagnostic, not a source-similarity score.
    metrics_available = visual is not None
    quality_ok = bool(checks['visual']) if metrics_available else False
    # Only catastrophic renderer divergence blocks acceptance independently.
    # Values below the stricter advisory target remain surfaced as warnings.
    renderer_ok = True if plan_exec is None else plan_exec >= 70.0
    deadline_ok = checks['deadline'] is True
    accepted = bool(metrics_available and quality_ok and renderer_ok and deadline_ok)
    warnings=[]
    for key in ('perceptual_color','edge','coverage','plan_execution'):
        if checks.get(key) is False:
            warnings.append(key)

    if not metrics_available:
        status = 'UNVERIFIED'
    elif accepted:
        status = 'PASS'
    elif not deadline_ok and not quality_ok:
        status = 'OVER_BUDGET_AND_BELOW_QUALITY'
    elif not deadline_ok:
        status = 'OVER_BUDGET'
    elif not quality_ok:
        status = 'BELOW_QUALITY_GATE'
    else:
        status = 'RENDERER_CORRECTNESS_FAIL'

    headroom = None if usable_f is None or projected is None else usable_f - projected
    return {
        'version': AUTO_TUNER_VERSION, 'status': status, 'accepted': accepted,
        'metrics_available': metrics_available, 'quality_gate_passed': bool(quality_ok),
        'deadline_gate_passed': bool(deadline_ok), 'renderer_gate_passed': bool(renderer_ok),
        'checks': checks, 'component_checks_advisory': True, 'diagnostic_warnings': tuple(warnings), 'gates': gates,
        'visual_accuracy_percent': visual, 'perceptual_color_accuracy_percent': perceptual,
        'edge_accuracy_percent': edge, 'coverage_percent': coverage,
        'plan_execution_accuracy_percent': plan_exec,
        'projected_draw_seconds': None if projected is None else round(projected, 3),
        'usable_deadline_seconds': None if usable_f is None else round(usable_f, 3),
        'schedule_headroom_seconds': None if headroom is None else round(headroom, 3),
        'selected_strategy': tuner.get('selected_strategy'), 'source_kind': features_meta.get('source_kind'),
        'replan_attempt': int(options.get('_auto_tuner_replan_attempt', 0) or 0),
    }


def _clear_plan_transients(out: dict[str, Any]) -> None:
    for key in (
        'pixel_accuracy_meta', 'adaptive_accuracy_meta', 'preview_delta_e_meta', 'preview_diagnostics_meta',
        'region_fill_meta', 'fill_regions', 'fill_timing_meta', 'extra_fast_meta', 'extra_fast_v2_meta',
        'operation_timing_meta', 'performance_profile', 'resource_scheduler_plan', 'deadline_runtime_meta',
        '_pixel_coverage_preview', '_pixel_error_preview', '_preview_quantized_target',
        '_accuracy_quantized_target_available', 'color_render_meta', 'adaptive_color_count_meta',
    ):
        out.pop(key, None)


def propose_rescue_options(plan: dict[str, Any], acceptance: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return one bounded second-pass configuration, or None.

    Deadline misses are rescued by Extra Fast 2.0 + lower detail/colour ceiling.
    Quality misses are rescued only when the first plan has meaningful time
    headroom, so the tuner never fixes colour/detail by knowingly breaking an
    already tight 75/80-second round.
    """
    options = plan.get('options') or {}
    tuner = options.get('auto_tuner_meta') or {}
    if not isinstance(tuner, dict) or not tuner.get('active'):
        return None
    attempt = int(options.get('_auto_tuner_replan_attempt', 0) or 0)
    if attempt >= 1:
        return None
    acceptance = acceptance or evaluate_plan_acceptance(plan)
    if acceptance.get('status') in ('PASS', 'UNVERIFIED'):
        return None
    perf = plan.get('performance_profile') or {}
    if bool(options.get('_preview_plan')) and _finite(perf.get('total_planning'), 0.0) >= 8.0:
        return None

    out = dict(options)
    _clear_plan_transients(out)
    out['_auto_tuner_replan_attempt'] = attempt + 1
    out['_auto_tuner_resolved'] = True
    out['auto_engine_resolved'] = True
    history = list(out.get('_auto_tuner_attempt_history') or ())
    history.append({k: acceptance.get(k) for k in ('status', 'visual_accuracy_percent', 'projected_draw_seconds',
                                                   'usable_deadline_seconds', 'schedule_headroom_seconds', 'selected_strategy')})
    out['_auto_tuner_attempt_history'] = history[-2:]

    deadline_fail = not bool(acceptance.get('deadline_gate_passed', True))
    quality_fail = not bool(acceptance.get('quality_gate_passed', True))
    if deadline_fail:
        out.update({
            'drawing_mode': 'Smart paths (recommended)', 'mode': 'Smart paths (recommended)', 'smart_paths': True, 'lines': True,
            'draw_quality': 'Balanced' if _finite(acceptance.get('usable_deadline_seconds'), 999) <= 82 else 'High likeness',
            'planning_resolution': 'Standard', 'quality': 'Balanced', 'detail': 8,
            'adaptive_detail': 'Strong simplify', 'speed': 'Fast', 'delay': base_delay('Fast'), 'precision': 'Normal',
            'extra_fast': True, 'extra_fast_v2': True, 'progressive_rendering': 'On',
            'stroke_optimizer': 'Smart merge', 'background_simplification': 'Strong',
            'background_fill': 'Balanced' if out.get('fill_tool_available') else 'Off', 'fill_engine': 'Closed regions v2',
        })
        current = max(4, int(_finite(out.get('_auto_tuner_color_ceiling', out.get('exact_color_limit_profile_ceiling')), 12)))
        floor = 4
        try:
            sf = tuner.get('source_features') or {}
            floor = max(4, len(tuple(sf.get('dominant_hues') or ())) + (2 if int(sf.get('tone_bins',1) or 1) >= 3 else 1) + 2)
        except Exception:
            pass
        reduced = max(floor, min(current, max(6, int(math.floor(current * .72)))))
        out['exact_color_limit_profile_ceiling'] = int(reduced); out['_auto_tuner_color_ceiling'] = int(reduced)
        rescue_name = 'deadline-rescue'
    elif quality_fail:
        headroom = _finite(acceptance.get('schedule_headroom_seconds'), 0.0)
        usable = max(1.0, _finite(acceptance.get('usable_deadline_seconds'), 1.0))
        projected = max(0.0, _finite(acceptance.get('projected_draw_seconds'), 0.0))
        # Timed plans need at least 15% spare budget before buying more quality.
        if acceptance.get('usable_deadline_seconds') is not None and headroom < max(3.0, usable * .15):
            return None
        source_kind = str((tuner.get('source_features') or {}).get('source_kind') or '')
        profile_group = str(tuner.get('profile_group') or '')
        try:
            aw, ah = map(int, plan.get('plan_area') or (0, 0))
            plan_pixels = max(0, aw) * max(0, ah)
        except Exception:
            plan_pixels = 0
        # When a texture-heavy browser plan uses less than roughly one third of
        # the usable budget, a bounded Pixel Accurate rescue can materially
        # improve source similarity while still leaving a large deadline margin.
        # This is intentionally disabled for Paint (custom RGB/tool overhead can
        # dominate there) and for large/unknown target rasters.
        pixel_rescue = (source_kind == 'photo / texture' and profile_group in ('browser','skribbl-fast','generic')
                        and 0 < plan_pixels <= 220_000 and projected <= usable * .32)
        if pixel_rescue:
            out.update({
                'draw_quality':'Pixel Accurate','planning_resolution':'Extreme',
                'quality':'Maximum detail','detail':10,'adaptive_detail':'Off',
                'background_simplification':'Off','color_grouping':'Accurate',
                'stroke_optimizer':'Travel only','speed':'Balanced','delay':base_delay('Balanced'),
                'precision':'High','extra_fast':False,'extra_fast_v2':False,'brush_px':1,
            })
            current = max(8, int(_finite(out.get('_auto_tuner_color_ceiling', out.get('exact_color_limit_profile_ceiling')), 16)))
            raised = min(32, max(current + 4, 24))
            out['exact_color_limit_profile_ceiling'] = int(raised); out['_auto_tuner_color_ceiling'] = int(raised)
            rescue_name = 'quality-rescue-pixel-accurate'
        else:
            q = str(out.get('draw_quality') or 'High likeness')
            out['draw_quality'] = {'Balanced':'High likeness', 'High likeness':'Maximum likeness'}.get(q, q)
            out['planning_resolution'] = 'High' if str(out.get('planning_resolution')) == 'Standard' else 'Ultra'
            out['quality'] = 'Maximum detail'; out['detail'] = 10; out['adaptive_detail'] = 'Preserve detail'
            out['speed'] = 'Balanced'; out['delay'] = base_delay('Balanced'); out['precision'] = 'High'
            if source_kind == 'flat illustration':
                out['drawing_mode'] = 'Shape paths'; out['mode'] = 'Shape paths'; out['smart_paths'] = False
                out['extra_fast'] = False; out['extra_fast_v2'] = False
            current = max(4, int(_finite(out.get('_auto_tuner_color_ceiling', out.get('exact_color_limit_profile_ceiling')), 16)))
            raised = min(32, current + (2 if usable <= 82 else 4))
            out['exact_color_limit_profile_ceiling'] = int(raised); out['_auto_tuner_color_ceiling'] = int(raised)
            rescue_name = 'quality-rescue'
    else:
        return None

    new_tuner = dict(tuner)
    new_tuner.update({
        'selected_strategy': rescue_name,
        'strategy_reason': f"Bounded second pass after {acceptance.get('status')}",
        'renderer': out.get('drawing_mode'), 'render_style': out.get('render_style'),
        'quick_sketch': bool(out.get('quick_sketch_auto') or str(out.get('render_style') or '') == 'Quick Sketch Fill + Contour'),
        'quick_sketch_style': out.get('quick_sketch_style'),
        'draw_quality': out.get('draw_quality'),
        'adaptive_detail': out.get('adaptive_detail'), 'detail_zoom': out.get('detail_zoom'), 'planning_resolution': out.get('planning_resolution'),
        'speed_strategy': out.get('speed'), 'extra_fast_2': bool(out.get('extra_fast_v2')),
        'color_ceiling': int(out.get('_auto_tuner_color_ceiling', 0) or 0), 'replan_attempt': attempt + 1,
    })
    out['auto_tuner_meta'] = new_tuner
    return out


def format_tuner_summary(meta: dict[str, Any] | None, acceptance: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    if not meta.get('active'):
        return ''
    bits = [f"Auto tuner: {meta.get('selected_strategy','Auto')}",
            f"{meta.get('renderer','renderer')}", f"{meta.get('draw_quality','quality')}",
            f"{meta.get('speed_strategy','speed')}", f"colors ≤{int(meta.get('color_ceiling',0) or 0)}"]
    if acceptance:
        status = str(acceptance.get('status') or 'UNVERIFIED')
        bits.insert(1, status)
        gate = (acceptance.get('gates') or {}).get('visual_accuracy_min_percent')
        if gate is not None:
            bits.append(f"visual gate ≥{float(gate):.0f}%")
        usable = acceptance.get('usable_deadline_seconds')
        projected = acceptance.get('projected_draw_seconds')
        if usable is not None and projected is not None:
            bits.append(f"{float(projected):.1f}/{float(usable):.1f}s")
    return ' · '.join(bits)
