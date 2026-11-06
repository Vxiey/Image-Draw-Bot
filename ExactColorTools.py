"""User-calibrated exact RGB/custom color controls.

Coordinates are stored relative to the target window anchor. v2 adds a visual
color-spectrum workflow: Image Draw Bot can sample the visible color field/slider
and click the point whose rendered RGB is nearest the requested drawing color.
Numeric R/G/B fields remain a deterministic fallback.
"""
from __future__ import annotations
import json,tempfile
from pathlib import Path
from CalibrationAnchors import validate_anchor,resolve_point
from RuntimePaths import data_dir
from ProfileStorage import safe_profile_key

SCHEMA=2
SUPPORTED_SCHEMAS=(1,2)
BASE_FIELDS=('OpenCustomColor','ConfirmColor')
RGB_FIELDS=('RedField','GreenField','BlueField')
SPECTRUM_FIELDS=('SpectrumTopLeft','SpectrumBottomRight')
BRIGHTNESS_FIELDS=('BrightnessTop','BrightnessBottom')
OPTIONAL_FIELDS=('Eyedropper','SelectedColorPreview','ActiveColorPreview')+BRIGHTNESS_FIELDS
ALL_FIELDS=BASE_FIELDS+RGB_FIELDS+SPECTRUM_FIELDS+OPTIONAL_FIELDS
# Kept for compatibility with callers/tests from v1.0.33.
CUSTOM_FIELDS=BASE_FIELDS+RGB_FIELDS


def file_for(profile_key):
    return data_dir()/f'exact-colors-{safe_profile_key(profile_key)}.json'


def _point(v,name):
    if not isinstance(v,(list,tuple)) or len(v)!=2 or any(type(n) is not int for n in v):
        raise ValueError(f'Invalid {name} position. Recalibrate exact color controls.')
    return [int(v[0]),int(v[1])]


def _has(controls,names):
    return all(name in controls for name in names)


def validate(data,profile_key=None):
    if not isinstance(data,dict) or int(data.get('version',0)) not in SUPPORTED_SCHEMAS:
        raise ValueError('Invalid exact color calibration.')
    if profile_key is not None and data.get('profile')!=profile_key:
        raise ValueError('Exact color calibration belongs to another profile.')
    anchor=validate_anchor(data.get('anchor'))
    controls=data.get('controls') or {};clean={}
    for name in ALL_FIELDS:
        if controls.get(name) is not None:clean[name]=_point(controls[name],name)
    # Normalize old schema files to current in-memory representation.
    return {'version':SCHEMA,'profile':str(data.get('profile','')),'anchor':anchor,'controls':clean}


def save(profile_key,controls,*,anchor,path=None):
    data={'version':SCHEMA,'profile':profile_key,'anchor':validate_anchor(anchor),'controls':{}}
    for name,value in controls.items():
        if name not in ALL_FIELDS:raise ValueError(f'Unsupported exact color control: {name}')
        data['controls'][name]=_point(value,name)
    clean=validate(data,profile_key);path=Path(path or file_for(profile_key));path.parent.mkdir(parents=True,exist_ok=True)
    tmp=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',delete=False,dir=path.parent,suffix='.tmp') as f:
            tmp=Path(f.name);json.dump(clean,f,ensure_ascii=False,indent=2);f.flush()
        tmp.replace(path)
    finally:
        if tmp:tmp.unlink(missing_ok=True)
    return clean


def load(profile_key,path=None):
    path=Path(path or file_for(profile_key));return validate(json.loads(path.read_text(encoding='utf-8')),profile_key)


def numeric_rgb_available(profile_key,path=None):
    try:controls=load(profile_key,path)['controls']
    except (OSError,ValueError):return False
    return _has(controls,BASE_FIELDS+RGB_FIELDS)


def spectrum_available(profile_key,path=None):
    try:controls=load(profile_key,path)['controls']
    except (OSError,ValueError):return False
    return _has(controls,BASE_FIELDS+SPECTRUM_FIELDS)


def brightness_available(profile_key,path=None):
    try:controls=load(profile_key,path)['controls']
    except (OSError,ValueError):return False
    return _has(controls,BRIGHTNESS_FIELDS)


def custom_rgb_available(profile_key,path=None):
    """Exact-color capability via visual spectrum or numeric RGB fields."""
    return spectrum_available(profile_key,path) or numeric_rgb_available(profile_key,path)


def resolve_image_custom_color_workflow(profile_name, profile_key, requested_workflow, *, render_preset='Auto', path=None):
    """Resolve automatic image-driven custom colors without widening target scope.

    Only Microsoft Paint is auto-promoted. A valid calibrated Edit colors
    spectrum or numeric RGB workflow is required. Manual render preset preserves
    an explicit ``Calibrated palette`` choice; Auto/Masterpiece/Extra fast may
    promote it to Adaptive exact so the current image's useful colors are selected
    automatically. Other targets are returned unchanged.
    """
    requested=str(requested_workflow or 'Calibrated palette')
    key=str(profile_key or '').strip().lower()
    paint=(str(profile_name or '').strip()=='Microsoft Paint' or key=='microsoft-paint')
    if not paint:
        return {'workflow':requested,'available':False,'auto_promoted':False,'profile_key':key,'reason':'not-microsoft-paint'}
    try:
        available=bool(custom_rgb_available(key or 'microsoft-paint',path))
    except Exception:
        available=False
    manual=str(render_preset or 'Auto').strip().lower()=='manual'
    promote=bool(available and not manual and requested=='Calibrated palette')
    workflow='Adaptive exact (recommended)' if promote else requested
    return {
        'workflow':workflow,'available':available,'auto_promoted':promote,
        'profile_key':key or 'microsoft-paint',
        'reason':('calibrated-custom-color-auto' if promote else ('custom-color-ready' if available else 'custom-color-unavailable')),
    }


def eyedropper_available(profile_key,path=None):
    try:return 'Eyedropper' in load(profile_key,path)['controls']
    except (OSError,ValueError):return False


def resolved_controls(profile_key,current_client_rect,path=None):
    data=load(profile_key,path);anchor=data['anchor']
    return {name:resolve_point(pos,anchor,current_client_rect) for name,pos in data['controls'].items()}
