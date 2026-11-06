"""Persisted Microsoft Paint tool positions used by Image Draw Bot.

Version 2 anchors controls to Paint's client rectangle.  Paint's Brushes control
is a dropdown, so automatic Brush selection uses two calibrated clicks:
Brushes menu -> concrete brush preset -> optional/required 100% opacity.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from RuntimePaths import data_dir, read_json, atomic_write_text
from CalibrationAnchors import validate_anchor, resolve_point
from CalibrationValidation import finite_confidence,point_in_rect

LEGACY_TOOL_FILE = data_dir() / 'paint-tools.json'
TOOL_FILE = data_dir() / 'paint-tools-microsoft-paint.json'
PAINT_TOOLS = ('Auto (recommended)', 'Use current tool', 'Brush', 'Pencil', 'Eraser', 'Fill')
AUTOMATIC_TOOLS = ('Auto (recommended)', 'Brush', 'Pencil', 'Eraser', 'Fill')


def _point(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(v) is not int for v in value):
        raise ValueError(f'Invalid {label} position. Recalibrate Paint tools.')
    x, y = value
    if not (-100000 <= x <= 100000 and -100000 <= y <= 100000):
        raise ValueError(f'Invalid {label} position. Recalibrate Paint tools.')
    return (x, y)


def validate_tool_calibration(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in (1,2,3):
        raise ValueError('Invalid Paint tool calibration. Recalibrate Paint tools.')
    version=data['version']
    tools=data.get('tools')
    if not isinstance(tools, dict):
        raise ValueError('Paint tool calibration is missing tool positions.')
    clean={'version':version,'tools':{}}
    # Legacy v1 is read only so Pencil/Eraser can still be inspected. Brush v1
    # is intentionally unsafe because one click only opens the Brushes dropdown.
    for name in ('Pencil','Eraser','Fill'):
        value=tools.get(name)
        if value is not None:clean['tools'][name]=list(_point(value,name))
    if version==1:
        value=tools.get('Brush')
        if value is not None:clean['legacy_brush']=list(_point(value,'Brush'))
    else:
        clean['anchor']=validate_anchor(data.get('anchor'))
        menu=data.get('brush_menu');preset=data.get('brush_preset')
        if menu is not None:clean['brush_menu']=list(_point(menu,'Brushes menu'))
        if preset is not None:clean['brush_preset']=list(_point(preset,'Brush preset'))
    opacity=data.get('opacity_100')
    if opacity is not None:clean['opacity_100']=list(_point(opacity,'100% opacity'))
    if version>=3:
        auto=data.get('auto')
        if isinstance(auto,dict):
            clean_auto={}
            for key in ('method','layout_signature'):
                if isinstance(auto.get(key),str):clean_auto[key]=auto[key]
            conf=auto.get('confidence')
            if conf is not None:clean_auto['confidence']=finite_confidence(conf)
            detected=auto.get('detected')
            if isinstance(detected,list):clean_auto['detected']=[str(x) for x in detected[:16]]
            if clean_auto:clean['auto']=clean_auto
    return clean


def load_tool_calibration(path=TOOL_FILE):
    path=Path(path)
    source=path
    if path==TOOL_FILE and not path.exists() and LEGACY_TOOL_FILE.exists():
        source=LEGACY_TOOL_FILE
    data=read_json(source,max_bytes=128*1024,max_items=2000)
    clean=validate_tool_calibration(data)
    # Safe one-time migration of the dedicated Paint calibration. No other
    # profile reads either filename.
    if source==LEGACY_TOOL_FILE and path==TOOL_FILE and clean.get('version',0)>=2:
        try:
            atomic_write_text(path,json.dumps(clean,ensure_ascii=False,indent=2,allow_nan=False))
        except OSError:pass
    return clean


def save_tool_calibration(tools, opacity_100=None, path=TOOL_FILE, *, anchor=None,
                          brush_menu=None, brush_preset=None, auto=None):
    """Save version-2 anchored calibration."""
    if anchor is None:
        raise ValueError('Paint tool calibration must be anchored to the Paint window. Recalibrate Paint tools.')
    data={'version':3,'tools':{},'anchor':validate_anchor(anchor)}
    for name,value in tools.items():
        if name not in ('Pencil','Eraser','Fill'):
            raise ValueError(f'Unsupported direct Paint tool: {name}')
        data['tools'][name]=list(_point(value,name))
    if brush_menu is not None:data['brush_menu']=list(_point(brush_menu,'Brushes menu'))
    if brush_preset is not None:data['brush_preset']=list(_point(brush_preset,'Brush preset'))
    if opacity_100 is not None:data['opacity_100']=list(_point(opacity_100,'100% opacity'))
    if auto is not None:data['auto']=dict(auto)
    clean=validate_tool_calibration(data)
    atomic_write_text(Path(path),json.dumps(clean,ensure_ascii=False,indent=2,allow_nan=False))
    return clean


def _resolve(value,data,current_client_rect,label):
    if current_client_rect is None:
        raise ValueError('The current Paint window geometry is unavailable. Select the drawing area again.')
    point=resolve_point(value,data['anchor'],current_client_rect)
    if not point_in_rect(point,current_client_rect):
        raise ValueError(f'The calibrated Paint {label} is outside the current client. Recalibrate Paint tools.')
    return point


def _auto_tool(data):
    """Choose the safest calibrated solid Paint tool.

    Pencil is preferred because it produces deterministic, opaque pixels and
    does not depend on which brush preset Paint last remembered. Brush is used
    only when its dropdown, concrete preset and 100% opacity point are all
    calibrated.
    """
    # Pencil is opaque by design in Paint and must not depend on the Brush opacity UI.
    # Requiring/clicking an opacity coordinate while Pencil is active can hit a different
    # toolbar control on newer Paint layouts and change the rendered color.
    if data.get('tools',{}).get('Pencil') is not None:
        return 'Pencil'
    if (data.get('opacity_100') is not None and data.get('brush_menu') is not None
            and data.get('brush_preset') is not None):
        return 'Brush'
    raise ValueError(
        'Auto (recommended) needs a calibrated Pencil, or a calibrated solid Brush preset + 100% opacity. '
        'Open Calibrate Paint tools first.'
    )


def build_tool_actions(selected_tool,path=TOOL_FILE,*,current_client_rect=None):
    """Return ordered clicks required before drawing.

    ``Auto (recommended)`` prefers Pencil because recent Microsoft Paint brush
    presets may be translucent even when black is selected. Brush is deliberately
    two-step because the modern Paint Brushes control is a dropdown.
    """
    if selected_tool not in PAINT_TOOLS:raise ValueError('Unknown Paint drawing tool.')
    if selected_tool=='Use current tool':return []
    try:data=load_tool_calibration(path)
    except (OSError,ValueError,json.JSONDecodeError) as error:
        if selected_tool=='Auto (recommended)':
            raise ValueError('Auto (recommended) is not calibrated yet. Open Calibrate Paint tools and capture Pencil, or Brush + 100% opacity.') from error
        raise ValueError('Calibrate Paint tools before using automatic tool selection.') from error
    if data['version']<2:
        raise ValueError('This Paint tool calibration is from an older version. Recalibrate Paint tools before automatic selection.')
    if selected_tool=='Auto (recommended)':
        selected_tool=_auto_tool(data)
    actions=[]
    if selected_tool=='Brush':
        if data.get('brush_menu') is None or data.get('brush_preset') is None:
            raise ValueError('Brush needs both Brushes menu and Brush preset positions. Recalibrate Paint tools.')
        actions.append(('brush-menu',_resolve(data['brush_menu'],data,current_client_rect,'Brushes menu')))
        actions.append(('brush-preset',_resolve(data['brush_preset'],data,current_client_rect,'Brush preset')))
    else:
        position=data['tools'].get(selected_tool)
        if position is None:raise ValueError(f'{selected_tool} is not calibrated. Open Calibrate Paint tools.')
        actions.append(('tool',_resolve(position,data,current_client_rect,selected_tool)))
    # Opacity belongs to the Brush workflow only. Pencil is deterministic/opaque
    # and clicking a saved opacity coordinate while Pencil is active is unsafe.
    if selected_tool=='Brush':
        if data.get('opacity_100') is None:
            raise ValueError('Brush requires a calibrated 100% opacity point. Recalibrate Paint tools.')
        actions.append(('opacity',_resolve(data['opacity_100'],data,current_client_rect,'100% opacity')))
    return actions
