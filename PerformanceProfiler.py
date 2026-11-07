"""Lightweight planning profiler for Image Draw Bot v1.0.27.

Profiler data is kept inside the plan options dictionary so it follows preview,
watchdog fallback and final plans without touching mouse execution.
"""
from __future__ import annotations
import time
from RuntimePaths import is_finite_number

PHASES = (
    'preprocessing',
    'color_planning',
    'shape_extraction',
    'path_optimization',
    'preview_rendering',
    'execution_estimate',
)


def begin(options):
    data = {'started': time.perf_counter(), 'timings': {}, 'marks': {}, 'total_planning': 0.0}
    options['_performance_profile'] = data
    return data


def start(options, phase):
    data = options.setdefault('_performance_profile', {'started': time.perf_counter(), 'timings': {}, 'marks': {}, 'total_planning': 0.0})
    token = time.perf_counter()
    data.setdefault('marks', {})[phase] = token
    return token


def stop(options, phase, token=None):
    now = time.perf_counter()
    data = options.setdefault('_performance_profile', {'started': now, 'timings': {}, 'marks': {}, 'total_planning': 0.0})
    marks = data.setdefault('marks', {})
    if token is None:
        if phase not in marks:
            return 0.0
        token = marks[phase]
    # Explicit stop tokens must be consumed once without erasing a newer
    # nested mark for the same phase. Keep plan metadata JSON-serializable.
    consumed = data.setdefault('stopped_tokens', [])
    identity = [phase, token]
    if identity in consumed:
        return 0.0
    consumed.append(identity)
    if marks.get(phase) == token:
        marks.pop(phase)
    elapsed = max(0.0, now - token)
    timings = data.setdefault('timings', {})
    timings[phase] = timings.get(phase, 0.0) + elapsed
    return elapsed


def finalize(options):
    now = time.perf_counter()
    data = options.setdefault('_performance_profile', {'started': now, 'timings': {}, 'marks': {}, 'total_planning': 0.0})
    data['total_planning'] = max(0.0, now - float(data.get('started', now)))
    timings = data.setdefault('timings', {})
    for phase in PHASES:
        timings.setdefault(phase, 0.0)
    return snapshot(options)


def snapshot(options):
    data = options.get('_performance_profile') or {}
    timings = dict(data.get('timings') or {})
    total = float(data.get('total_planning') or 0.0)
    return {'timings': timings, 'total_planning': total}


def format_profile(profile, compact=False):
    if not profile:
        return 'Profiler unavailable'
    timings = profile.get('timings') or {}
    total = float(profile.get('total_planning') or 0.0)
    labels = (
        ('preprocessing', 'preprocess'),
        ('color_planning', 'colors'),
        ('shape_extraction', 'shapes'),
        ('path_optimization', 'paths'),
        ('preview_rendering', 'preview'),
        ('execution_estimate', 'estimate'),
    )
    if compact:
        parts = [f"{label} {float(timings.get(key,0))*1000:.0f}ms" for key,label in labels]
        return f"total {total:.2f}s · " + ' · '.join(parts)
    lines = [f"Total planning: {total:.3f} s"]
    for key,label in labels:
        seconds = float(timings.get(key, 0.0))
        share = (seconds / total * 100.0) if total > 0 else 0.0
        lines.append(f"{label}: {seconds:.3f} s ({share:.1f}%)")
    return '\n'.join(lines)


def dominant_phase(profile):
    timings = (profile or {}).get('timings') or {}
    if not timings:
        return None, 0.0
    measured = {name: value for name in PHASES if is_finite_number(value := timings.get(name)) and value > 0}
    if not measured:
        return None, 0.0
    key = max(measured, key=measured.get)
    return key, float(measured[key])
