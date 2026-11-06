"""Drawing profiles, profile-specific UI guidance and safe renderer defaults.

Profiles never contain screen coordinates. They only describe semantics, copy and
conservative planning defaults. Native locations are still calibrated explicitly.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
import uuid

MAX_CUSTOM_PROFILE_BYTES = 1024 * 1024
MAX_CUSTOM_PROFILES = 1000
CUSTOM_PROFILE_LOCK = threading.RLock()

PROFILES={
 'Microsoft Paint':('microsoft-paint','#087e8b','Desktop Paint profile. Keep the toolbar visible, use the final window size, calibrate tools/colors and select only the canvas.'),
 'Other drawing app':('generic','#087e8b','Generic calibrated drawing-app profile. Keep the palette and normal brush visible in a fixed layout.'),
 'Gartic Phone':('gartic-phone','#7048a5','Gartic Phone profile. Auto Setup detects canvas/palette/brush controls and the per-game input engine tunes browser timing automatically.'),
 'Skribbl.io':('skribbl','#2563a6','Skribbl.io quality profile. Auto Setup verifies canvas/palette/brush size and uses Skribbl-specific input timing.'),
 'Skribbl.io Fast':('skribbl-fast','#1f9d8a','Fast Skribbl profile. Prioritizes recognizable shapes, reduced colors, automatic brush size and the fastest Skribbl-specific input timing.'),
 'SketchHeads':('sketchheads','#6f63ff','SketchHeads profile. Auto setup detects the safe canvas, true color row and brush-size controls; input timing is tuned separately from other games.'),
 'Sketchful.io':('sketchful','#b14f22','Sketchful.io profile. Auto Setup verifies the visible palette/canvas and re-scans before drawing after zoom/resize changes.'),
 'Drawize':('drawize','#287646','Drawize profile. Keep the drawing toolbar visible, calibrate the visible controls and select only the canvas.'),
 'Gartic.io':('gartic-io','#1768a2','Gartic.io profile. Keep the browser layout fixed, capture the palette and select only the drawable canvas.'),
 'Kleki':('kleki','#5b6fa8','Kleki browser painting profile. Calibrate the visible brush/fill/colors and select only the canvas; no automatic layout coordinates are assumed.'),
 'Magma':('magma','#b7492f','Magma collaborative drawing profile. Calibrate the current canvas/tools/colors per session layout and keep the browser geometry stable.')}

# UI-only metadata. Emoji are deliberately text glyphs so the package does not
# need extra icon/image assets and remains portable in the ZIP build.
PROFILE_UI={
 'Microsoft Paint': dict(icon='🎨', badge='Desktop app', prepare_title='Prepare Microsoft Paint',
     prepare_subtitle='Calibrate Paint tools/colors, select only the canvas, then test.',
     tool_button='🖌  Calibrate Paint tools', palette_button='🎨  Read Paint colors / palette',
     area_button='▣  Select Paint canvas', tip='Best for high-quality local drawings. Match Image Draw Bot brush width to Paint.'),
 'Other drawing app': dict(icon='🧩', badge='Custom / generic', prepare_title='Prepare drawing app',
     prepare_subtitle='Calibrate the visible controls/palette, then select only the drawable area.',
     tool_button='🧰  Calibrate Brush / Fill', palette_button='🎨  Read colors / palette',
     area_button='▣  Select drawing area', tip='Use this when no dedicated profile exists. Keep the app layout fixed after calibration.'),
 'Gartic Phone': dict(icon='☎️', badge='Browser game', prepare_title='Prepare Gartic Phone',
     prepare_subtitle='Select/confirm the canvas once. Auto Setup handles the 72-color palette and brush size; manual tool capture is fallback-only.',
     tool_button='🧰  Calibrate Gartic tools', palette_button='🎨  Read Gartic palette',
     area_button='▣  Select Gartic canvas', tip='Gartic reference: 6×12 palette, wide white canvas (~1.79:1), Brush top-left and Fill in the right tool panel. Turbo batches colors and uses dual-axis runs.'),
 'Skribbl.io': dict(icon='✏️', badge='Browser game', prepare_title='Prepare Skribbl.io',
     prepare_subtitle='Keep the game visible and select/confirm the canvas once; palette and brush size are handled automatically.',
     tool_button='🧰  Calibrate Skribbl tools', palette_button='🎨  Read Skribbl palette',
     area_button='▣  Select Skribbl canvas', tip='Quality preset: Better Shapes v2 with progressive passes and a reduced palette.'),
 'Skribbl.io Fast': dict(icon='⚡', badge='Fast browser preset', prepare_title='Prepare Skribbl.io Fast',
     prepare_subtitle='Select/confirm the canvas; Turbo auto-detects palette/brush controls and batches colors into long continuous runs.',
     tool_button='🧰  Calibrate Skribbl tools', palette_button='🎨  Read Skribbl palette',
     area_button='▣  Select Skribbl canvas', tip='Turbo preset: calibrated palette only, few color switches, compressed raster runs and a 60-second target with reserve.'),
 'SketchHeads': dict(icon='🖍️', badge='Browser game', prepare_title='Prepare SketchHeads',
     prepare_subtitle='Select the game canvas once; Auto setup detects the visible color row and keeps the top/bottom UI outside the safe canvas.',
     tool_button='🧰  Manual tool fallback', palette_button='✨  Auto setup colors',
     area_button='▣  Select / confirm SketchHeads canvas', tip='Normal use needs no manual swatch capture. Auto setup detects the bottom palette row and uses a conservative safe canvas.'),
 'Sketchful.io': dict(icon='🖍️', badge='Browser game', prepare_title='Prepare Sketchful.io',
     prepare_subtitle='Lock browser zoom/layout, calibrate the visible palette and select only the canvas.',
     tool_button='🧰  Calibrate Sketchful tools', palette_button='🎨  Read Sketchful palette',
     area_button='▣  Select Sketchful canvas', tip='Shape paths are tuned for broad forms first, then contours and details.'),
 'Drawize': dict(icon='🟢', badge='Browser game', prepare_title='Prepare Drawize',
     prepare_subtitle='Keep the toolbar visible, calibrate controls/colors and select only the drawable canvas.',
     tool_button='🧰  Calibrate Drawize tools', palette_button='🎨  Read Drawize palette',
     area_button='▣  Select Drawize canvas', tip='Balanced shape rendering reduces mouse actions while retaining clear contours.'),
 'Gartic.io': dict(icon='🟦', badge='Browser game', prepare_title='Prepare Gartic.io',
     prepare_subtitle='Keep browser layout stable, capture the palette and select only the drawable canvas.',
     tool_button='🧰  Calibrate Gartic.io tools', palette_button='🎨  Read Gartic.io palette',
     area_button='▣  Select Gartic.io canvas', tip='Progressive Shape paths make the subject readable before small details are added.'),
 'Kleki': dict(icon='🖌️', badge='Browser painting app', prepare_title='Prepare Kleki',
     prepare_subtitle='Use manual tool/color calibration, then select only the drawable canvas. One-click layout detection is intentionally disabled until verified.',
     tool_button='🧰  Calibrate Kleki tools', palette_button='🎨  Read Kleki colors',
     area_button='▣  Select Kleki canvas', tip='Dedicated isolated profile. Browser layout, tool anchors, palette and timing data never leak to other targets.'),
 'Magma': dict(icon='🌋', badge='Collaborative browser app', prepare_title='Prepare Magma',
     prepare_subtitle='Open the intended collaborative canvas, calibrate visible tools/colors and select only the drawable canvas.',
     tool_button='🧰  Calibrate Magma tools', palette_button='🎨  Read Magma colors',
     area_button='▣  Select Magma canvas', tip='Dedicated isolated profile. Recalibrate when collaborative UI panels, zoom or canvas layout move.'),
}

# Applied before reading a profile's saved settings. A user's saved settings still
# win, except Manual preview remains a safety hard-lock elsewhere in DrawBot.
PROFILE_DEFAULTS={
 'Microsoft Paint': dict(mode='Shape paths', shape_model='Better shapes v2', shape_order='Fill first', progressive_rendering='On',
     quality='High detail', speed='Balanced', stroke_optimizer='Auto', adaptive_detail='Auto', visual_verification='Strict', precision='High', draw_quality='High likeness', planning_resolution='High', resource_scheduler='Auto',
     background_fill='Conservative', fill_engine='Closed regions v2', background_simplification='Balanced', color_grouping='Smart',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', exact_color_limit='Auto', time_budget_mode='Manual', target_stroke_count='Auto', max_stroke_cap='10000'),
 'Other drawing app': dict(mode='Smart paths (recommended)', shape_model='Auto', progressive_rendering='Auto',
     quality='Balanced', speed='Balanced', stroke_optimizer='Auto', adaptive_detail='Auto', visual_verification='Auto', precision='High', draw_quality='High likeness', planning_resolution='High', resource_scheduler='Auto',
     background_fill='Conservative', background_simplification='Balanced', color_grouping='Smart',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Manual'),
 'Gartic Phone': dict(mode='Smart paths (recommended)', shape_model='Better shapes v2', progressive_rendering='Off', planning_watchdog='On',
     quality='Balanced', speed='Fast', stroke_optimizer='Smart merge', adaptive_detail='Strong simplify', visual_verification='Off', precision='Normal', draw_quality='Balanced', planning_resolution='Standard', resource_scheduler='Auto',
     background_fill='Off', background_simplification='Strong', color_grouping='Reduced palette',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Calibrated palette', time_budget_mode='Gartic Phone Fast', max_stroke_cap='2500', target_stroke_count='Auto', target_stroke_custom='900', exact_color_limit='Auto'),
 'Skribbl.io': dict(mode='Shape paths', shape_model='Better shapes v2', progressive_rendering='On',
     quality='Balanced', speed='Fast', stroke_optimizer='Auto', adaptive_detail='Preserve detail', visual_verification='Auto', precision='Normal', draw_quality='High likeness', planning_resolution='Standard', resource_scheduler='Auto',
     background_fill='Off', background_simplification='Balanced', color_grouping='Reduced palette',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Skribbl Default', max_stroke_cap='2500', exact_color_limit='Auto'),
 'Skribbl.io Fast': dict(mode='Smart paths (recommended)', shape_model='Better shapes v2', progressive_rendering='Off', planning_watchdog='On',
     max_stroke_cap='1000', time_budget_mode='Skribbl 60', target_stroke_count='Auto', target_stroke_custom='650', exact_color_limit='Auto',
     quality='Balanced', speed='Fast', stroke_optimizer='Smart merge', adaptive_detail='Strong simplify', visual_verification='Off', precision='Normal', draw_quality='Balanced', cpu_workers='Auto', cpu_engine='Threads',
     planning_resolution='Standard', resource_scheduler='Auto', background_fill='Off', background_simplification='Strong', color_grouping='Reduced palette',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Calibrated palette'),
 'SketchHeads': dict(mode='Smart paths (recommended)', shape_model='Better shapes v2', progressive_rendering='Off',
     quality='Balanced', speed='Fast', stroke_optimizer='Smart merge', adaptive_detail='Strong simplify', visual_verification='Off', precision='Normal', draw_quality='Balanced', planning_resolution='Standard', resource_scheduler='Auto',
     background_fill='Off', background_simplification='Strong', color_grouping='Reduced palette',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Calibrated palette', time_budget_mode='60 sec', max_stroke_cap='1000'),
 'Sketchful.io': dict(mode='Shape paths', shape_model='Better shapes v2', progressive_rendering='On',
     quality='Balanced', speed='Fast', stroke_optimizer='Auto', adaptive_detail='Balanced', visual_verification='Auto', precision='Normal', draw_quality='Balanced', planning_resolution='Standard', resource_scheduler='Auto',
     background_fill='Off', background_simplification='Balanced', color_grouping='Reduced palette',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Manual', max_stroke_cap='5000'),
 'Drawize': dict(mode='Shape paths', shape_model='Better shapes v2', progressive_rendering='On',
     quality='Balanced', speed='Balanced', stroke_optimizer='Auto', adaptive_detail='Balanced', visual_verification='Auto', precision='Normal', draw_quality='Balanced', planning_resolution='Standard', resource_scheduler='Auto',
     background_fill='Conservative', background_simplification='Balanced', color_grouping='Smart',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Manual', max_stroke_cap='5000'),
 'Gartic.io': dict(mode='Shape paths', shape_model='Better shapes v2', progressive_rendering='On',
     quality='Balanced', speed='Fast', stroke_optimizer='Auto', adaptive_detail='Strong simplify', visual_verification='Auto', precision='Normal', draw_quality='Balanced', planning_resolution='Standard', resource_scheduler='Auto',
     background_fill='Off', background_simplification='Strong', color_grouping='Reduced palette',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Manual', max_stroke_cap='2500'),
 'Kleki': dict(mode='Shape paths', shape_model='Better shapes v2', progressive_rendering='On',
     quality='High detail', speed='Balanced', stroke_optimizer='Smart merge', adaptive_detail='Preserve detail', visual_verification='Auto', precision='High', draw_quality='High likeness', planning_resolution='High', resource_scheduler='Auto',
     background_fill='Conservative', background_simplification='Conservative', color_grouping='Smart',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Manual', max_stroke_cap='10000'),
 'Magma': dict(mode='Shape paths', shape_model='Better shapes v2', progressive_rendering='On',
     quality='High detail', speed='Balanced', stroke_optimizer='Smart merge', adaptive_detail='Preserve detail', visual_verification='Auto', precision='High', draw_quality='High likeness', planning_resolution='High', resource_scheduler='Auto',
     background_fill='Conservative', background_simplification='Conservative', color_grouping='Smart',
     color_rendering='Perceptual match', color_fidelity='Faithful', color_layers='Off', custom_color_workflow='Adaptive exact (recommended)', time_budget_mode='Manual', max_stroke_cap='10000'),
}


def profile_ui(name):
    return dict(PROFILE_UI.get(name, dict(icon='🧩', badge='Custom profile', prepare_title='Prepare drawing app',
        prepare_subtitle='Calibrate the visible palette/tools and select only the drawable area.',
        tool_button='🧰  Calibrate Brush / Fill', palette_button='🎨  Read colors / palette',
        area_button='▣  Select drawing area', tip='Keep the app window and layout fixed after calibration.')))


def profile_defaults(name):
    return dict(PROFILE_DEFAULTS.get(name, PROFILE_DEFAULTS['Other drawing app']))


def clean_profile_name(name):
    if not isinstance(name, str):
        raise ValueError('Choose a profile name containing 1–50 characters.')
    if any(unicodedata.category(ch).startswith('C') for ch in name):
        raise ValueError('Choose a profile name containing 1–50 printable characters.')
    name = name.strip()
    if not 1 <= len(name) <= 50:
        raise ValueError('Choose a profile name containing 1–50 printable characters.')
    return name


def validate_custom_profile_name(name):
    name = clean_profile_name(name)
    if name.casefold() in {existing.casefold() for existing in PROFILES}:
        raise ValueError('Choose a unique name containing 1–50 characters.')
    return name


def _register_custom_profile(name, key):
    PROFILES[name] = (key, '#087e8b', 'Custom profile: select a normal brush, read the colors and select the drawing area.')
    PROFILE_UI[name] = profile_ui('__custom__')


def current_custom_profile_registry(registry_path):
    """Read and merge the current registry without publishing either state.

    Callers hold CUSTOM_PROFILE_LOCK until file publication and registration
    finish. A failed startup read must never turn the next Add/Import into a
    replacement of profiles that are still safely stored on disk.
    """
    try:
        stored = _read_custom_profile_registry(registry_path)
    except FileNotFoundError:
        stored = {}
    data = {}
    names = {n.casefold(): (n, v[0]) for n, v in PROFILES.items()
             if not v[0].startswith('custom-')}
    owners = {v[0]: n for n, v in PROFILES.items() if not v[0].startswith('custom-')}
    current = {n: v[0] for n, v in PROFILES.items() if v[0].startswith('custom-')}
    for entries in (stored, current):
        for raw_name, key in entries.items():
            entry_name = clean_profile_name(raw_name)
            if not isinstance(key, str) or not re.fullmatch(r'custom-[a-f0-9]{32}', key):
                raise ValueError('The saved profile registry contains an invalid storage key. It was not changed.')
            folded = entry_name.casefold()
            previous = names.get(folded)
            if previous is not None:
                if entries is current and previous == (entry_name, key) and data.get(entry_name) == key:
                    continue
                raise ValueError('The saved profile registry has conflicting names or storage keys. It was not changed.')
            if key in owners:
                raise ValueError('The saved profile registry has conflicting names or storage keys. It was not changed.')
            names[folded] = (entry_name, key)
            owners[key] = entry_name
            data[entry_name] = key
    if len(data) > MAX_CUSTOM_PROFILES:
        raise ValueError('Too many custom profiles. The saved registry was not changed.')
    return data


def prepare_custom_profile(name, registry_path):
    """Prepare one new registration while the caller holds the registry lock."""
    name = validate_custom_profile_name(name)
    data = current_custom_profile_registry(registry_path)
    if name.casefold() in {entry.casefold() for entry in data}:
        raise ValueError('Choose a unique name containing 1–50 characters.')
    if len(data) >= MAX_CUSTOM_PROFILES:
        raise ValueError('Too many custom profiles.')
    key = 'custom-' + uuid.uuid4().hex
    if key in data.values():
        raise ValueError('Could not create a unique profile storage key. Try again.')
    data[name] = key
    return name, key, data


def _unique_profile_object(pairs):
    result = {}
    for name, key in pairs:
        if name in result:
            raise ValueError('Duplicate profile registry entry.')
        result[name] = key
    return result


def _read_custom_profile_registry(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_CUSTOM_PROFILE_BYTES + 1)
    if len(raw) > MAX_CUSTOM_PROFILE_BYTES:
        raise ValueError('The saved profile registry is too large. It was not changed.')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_profile_object)
    except RecursionError as error:
        raise ValueError('The saved profile registry is too deeply nested. It was not changed.') from error
    if not isinstance(data, dict) or len(data) > MAX_CUSTOM_PROFILES:
        raise ValueError('The saved profile registry is invalid or has too many profiles. It was not changed.')
    return data


def register_custom_profiles(data):
    """Expose an already validated and successfully published registration."""
    for name, key in data.items():
        _register_custom_profile(name, key)


def load_custom_profiles(path):
    try:
        data = _read_custom_profile_registry(path)
        owners = {v[0] for v in PROFILES.values()}
        names = {name.casefold() for name in PROFILES}
        for name,key in data.items():
            if not isinstance(key, str) or not re.fullmatch(r'custom-[a-f0-9]{32}', key) or key in owners:
                continue
            try:
                name = clean_profile_name(name)
            except ValueError:
                continue
            folded = name.casefold()
            if folded in names:
                continue
            _register_custom_profile(name, key)
            owners.add(key)
            names.add(folded)
    except (OSError, ValueError, RecursionError):
        return


def add_custom_profile(name,path):
    from RuntimePaths import atomic_write_text
    with CUSTOM_PROFILE_LOCK:
        name, key, data = prepare_custom_profile(name, path)
        atomic_write_text(path,json.dumps(data,ensure_ascii=False))
        register_custom_profiles(data)
