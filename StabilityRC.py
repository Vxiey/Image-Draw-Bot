"""Release-candidate stability helpers for Image Draw Bot v1.0.81.

Pure helpers keep migration/cleanup behavior testable without Windows input.
"""
from __future__ import annotations

SETTINGS_SCHEMA = 2


class UnsupportedSettingsSchema(ValueError):
    pass


def migrate_settings(data):
    """Normalize settings from older beta builds without trusting unknown types."""
    if not isinstance(data,dict):return {}
    out=dict(data)
    schema=out.get('settings_schema',0)
    if type(schema) is not int or not 0<=schema<=SETTINGS_SCHEMA:
        raise UnsupportedSettingsSchema('Unsupported settings schema; this build cannot rewrite it safely.')
    # Historical names accepted by older builds.
    aliases={'max_time':'max_seconds','brush_width':'brush_px','drawing_mode':'mode'}
    for old,new in aliases.items():
        if new not in out and old in out:out[new]=out[old]
        out.pop(old,None)
    # Retired automatic drop flags must never restore input authorization.
    for key in ('draw_immediately','auto_draw','drop_action_pending','manual_drop_in_start','full_draw_armed'):
        out.pop(key,None)
    out['settings_schema']=SETTINGS_SCHEMA
    return out


def safe_release_and_disarm(mouse, *, dry_run=False, logger=None):
    """Best-effort mouse-up followed by unconditional native-input disarm."""
    errors=[]
    if mouse is None:return errors
    if not dry_run and hasattr(mouse,'release'):
        try:mouse.release()
        except Exception as error:errors.append(('release',error))
    if hasattr(mouse,'disarm_input'):
        try:mouse.disarm_input()
        except Exception as error:errors.append(('disarm',error))
    if logger:
        for phase,error in errors:
            try:logger(f'RC cleanup {phase} failed safely: {error!r}')
            except Exception:pass
    return errors


def current_completion(current_activity, completed_activity):
    """Only the worker that owns the busy state may clear it."""
    return completed_activity is None or completed_activity==current_activity


def run_start_stop_model(cycles=128):
    """Pure stress model used by RC tests; returns final lifecycle invariants."""
    activity=None;armed=False;pending=False
    for _ in range(max(0,int(cycles))):
        if activity is not None:raise AssertionError('overlapping activity')
        armed=True;pending=True;activity='draw'
        # stop must revoke all authorization before activity clears
        armed=False;pending=False;activity=None
    return {'activity':activity,'armed':armed,'pending':pending,'cycles':max(0,int(cycles))}
