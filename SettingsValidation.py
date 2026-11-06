"""Semantic boundaries shared by local settings and portable profiles."""
from __future__ import annotations

import math
from copy import deepcopy
from contextlib import contextmanager

BOOLEAN_SETTINGS=frozenset(('adaptive_deadline_renderer','use_region_fill_engine',
    'auto_clear_canvas','portrait_focus','skip_white','outline','paint_simple',
    'read_gartic_timer','preview_show_background','preview_show_fill','preview_show_strokes'))
INTEGER_TEXT_SETTINGS=frozenset(('brush_px','max_seconds','target_stroke_custom',
                                'ram_custom_mb','exact_color_limit','deadline_safety_reserve'))
ADDITIONAL_VARIABLES=('use_region_fill_engine','fill_aggressiveness','detail_zoom',
    'quick_sketch_style','quick_sketch_fill_preference','preview_mode','auto_clear_canvas')


def validated_settings(data, *, strict=False):
    """Remove malformed local fields, or reject them before profile publication.

    Choice membership remains with the corresponding domain validators. This
    boundary excludes containers/coercible booleans/oversized scalar values so
    one corrupt field cannot abort unrelated valid local settings.
    """
    from ProfileIsolation import SETTING_NAMES, EXTRA_DEFAULTS
    from StabilityRC import migrate_settings
    if not isinstance(data,dict):
        raise ValueError('Settings must be a JSON object.')
    data=migrate_settings(data)
    variable_names=set(SETTING_NAMES)|set(ADDITIONAL_VARIABLES)
    out={}
    def invalid(name):
        if strict:raise ValueError(f'Invalid setting value: {name}.')
    for name,value in data.items():
        valid=True
        if name in BOOLEAN_SETTINGS:
            valid=type(value) is bool
        elif name=='contrast':
            try:valid=type(value) in (int,float) and math.isfinite(value) and .5<=value<=2
            except OverflowError:valid=False
        elif name in INTEGER_TEXT_SETTINGS:
            valid=((isinstance(value,str) and len(value)<=40) or
                   (type(value) is int and abs(value)<=10**12))
        elif name in variable_names:
            valid=isinstance(value,str) and len(value)<=200
        elif name=='corners':
            valid=value is None or (isinstance(value,(list,tuple)) and len(value)==2 and all(
                isinstance(point,(list,tuple)) and len(point)==2 and all(
                    type(coordinate) is int and abs(coordinate)<=1_000_000 for coordinate in point)
                for point in value) and value[0][0]!=value[1][0] and value[0][1]!=value[1][1])
        elif name=='canvas_anchor_detection':
            valid=value is None or isinstance(value,dict)
        elif name=='profile_extras':
            if not isinstance(value,dict):
                invalid(name);continue
            extra={}
            for key,item in value.items():
                default=EXTRA_DEFAULTS.get(key)
                if key not in EXTRA_DEFAULTS:
                    if strict:raise ValueError(f'Unknown profile display setting: {key}.')
                    continue
                ok=type(item) is type(default)
                if key=='ui_mode':ok=ok and item in ('Simple','Advanced','Developer')
                if key=='subject_focus':ok=ok and item in ('Off','Subject first','Subject only')
                if ok:extra[key]=item
                else:invalid(f'{name}.{key}')
            value=extra
        if valid:out[name]=deepcopy(value)
        else:invalid(name)
    return out


@contextmanager
def settings_application(app):
    """Restore the previous UI values if applying a settings document fails."""
    from ProfileIsolation import SETTING_NAMES, EXTRA_DEFAULTS
    saved=[]
    for name in dict.fromkeys((*SETTING_NAMES,*ADDITIONAL_VARIABLES,*EXTRA_DEFAULTS)):
        variable=getattr(app,name,None)
        if callable(getattr(variable,'get',None)) and callable(getattr(variable,'set',None)):
            saved.append((variable,variable.get()))
    missing=object()
    attributes={name:deepcopy(getattr(app,name,missing)) if hasattr(app,name) else missing
                for name in ('saved_area','canvas_anchor_detection')}
    was_applying=getattr(app,'profile_change_in_progress',False)
    app.profile_change_in_progress=True
    try:
        yield
    except BaseException as error:
        for variable,value in reversed(saved):
            try:
                if variable.get()!=value:variable.set(value)
            except Exception as cleanup:
                error.add_note(f'Settings rollback failed: {type(cleanup).__name__}.')
        for name,value in attributes.items():
            if value is missing:
                if hasattr(app,name):delattr(app,name)
            else:setattr(app,name,value)
        raise
    finally:
        app.profile_change_in_progress=was_applying
