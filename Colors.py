import re

allColors = []

_HEX_DIGITS = frozenset('0123456789abcdefABCDEF')
_FUNCTION_COLOR = re.compile(r'(?i)(?:rgb|rgba|argb)\s*\(')


def _channel(value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError('Color channels must be integers from 0 to 255.')
    return value


def argb_to_rgb(value, background=(255, 255, 255)):
    """Convert ARGB to visible RGB by compositing alpha over *background*.

    Accepted ARGB inputs: ``(A,R,G,B)``, ``#AARRGGBB``, ``AARRGGBB`` and a
    32-bit ``0xAARRGGBB`` integer.  White is the default background because
    Image Draw Bot previews/source transparency on a white drawing canvas.
    """
    bg=tuple(_channel(v) for v in background)
    if len(bg)!=3:raise ValueError('ARGB background must contain three RGB channels.')
    if isinstance(value,str):
        text=value.strip().replace('_','')
        if text.startswith('#'):text=text[1:]
        elif text.lower().startswith('0x'):text=text[2:]
        if len(text)!=8 or any(ch not in _HEX_DIGITS for ch in text):
            raise ValueError('ARGB hex colors must use AARRGGBB.')
        try:channels=tuple(int(text[i:i+2],16) for i in range(0,8,2))
        except ValueError:raise ValueError('Invalid ARGB hex color.') from None
    elif type(value) is int:
        if not 0<=value<=0xffffffff:raise ValueError('ARGB integer must be 0x00000000–0xFFFFFFFF.')
        channels=((value>>24)&255,(value>>16)&255,(value>>8)&255,value&255)
    else:
        try:channels=tuple(value)
        except TypeError:raise ValueError('ARGB must contain alpha, red, green and blue channels.') from None
        if len(channels)!=4:raise ValueError('ARGB must contain four channels: A, R, G, B.')
        channels=tuple(_channel(v) for v in channels)
    alpha,r,g,b=channels
    if alpha==255:return r,g,b
    if alpha==0:return bg
    return tuple(round((channel*alpha + base*(255-alpha))/255)
                 for channel,base in zip((r,g,b),bg))


def normalize_rgb(value, background=(255,255,255)):
    """Return an RGB tuple from RGB or ARGB values.

    RGB: 3-item sequence, ``#RRGGBB``/``RRGGBB`` or ``0xRRGGBB`` integer.
    ARGB: 4-item ``(A,R,G,B)`` sequence, 8-digit hex, or 32-bit integer.
    """
    if isinstance(value,str):
        raw=value.strip()
        text=raw.replace('_','')
        # Named Color Intelligence adds tolerant CSS4/Tk/X11 names plus explicit
        # rgb()/rgba()/argb() forms. Keep legacy comma lists and AARRGGBB semantics
        # unchanged so existing calibration/settings files remain compatible.
        if _FUNCTION_COLOR.match(raw):
            from NamedColorIntelligence import parse_named_color_text
            return parse_named_color_text(raw,background=background)
        # Also accept UI-friendly channel notation such as "255, 20, 30" or
        # "(128, 255, 20, 30)". Four bare channels are ARGB, not RGBA.
        channel_text=text.strip('()[]{} ')
        if ',' in channel_text:
            try:parts=tuple(int(part.strip()) for part in channel_text.split(','))
            except ValueError:raise ValueError('RGB/ARGB channel lists must contain integers.') from None
            return normalize_rgb(parts,background)
        prefixed_hash=text.startswith('#')
        prefixed_hex=prefixed_hash or text.lower().startswith('0x')
        if prefixed_hash:text=text[1:]
        elif text.lower().startswith('0x'):text=text[2:]
        # CSS short hex is unambiguous with a # prefix. #RGBA uses standard
        # RGBA order, while historical 8-digit Image Draw Bot hex stays AARRGGBB.
        if prefixed_hash and len(text) in (3,4):
            from NamedColorIntelligence import parse_named_color_text
            return parse_named_color_text('#'+text,background=background)
        hexadecimal=bool(text) and all(ch in _HEX_DIGITS for ch in text)
        if len(text)==8 and hexadecimal:
            return argb_to_rgb(text,background)
        if len(text)==6 and hexadecimal:
            return tuple(int(text[i:i+2],16) for i in range(0,6,2))
        if prefixed_hex:
            raise ValueError('Hex colors must contain only hexadecimal RGB/ARGB digits.')
        # Any non-hex string now gets a deterministic static named-colour lookup.
        # This does not add the named colour to allColors or the render palette.
        try:
            from NamedColorIntelligence import resolve_named_color
            return resolve_named_color(raw)
        except ValueError:
            raise ValueError('Use RGB/ARGB, CSS short hex, or a valid CSS4/Tk/X11 color name.') from None
    if type(value) is int:
        if not 0<=value<=0xffffffff:raise ValueError('Color integer is outside 0x00000000–0xFFFFFFFF.')
        if value>0xffffff:return argb_to_rgb(value,background)
        return (value>>16)&255,(value>>8)&255,value&255
    try:values=tuple(value)
    except TypeError:raise ValueError('Color must be RGB or ARGB.') from None
    if len(values)==4:return argb_to_rgb(values,background)
    if len(values)!=3:raise ValueError('Color must contain RGB or ARGB channels.')
    return tuple(_channel(v) for v in values)

class Color:
    def __init__(self, name, r, g, b):
        self.name = name
        self.R, self.G, self.B = normalize_rgb((r,g,b))
        self.RGB = (self.R, self.G, self.B)
        self.x = int()
        self.y = int()
        allColors.append(self)

    def printData(self):
        print(f"{self.name}: X: {self.x} Y: {self.y}")

black =      Color("Black",0,0,0)
gray =       Color("Gray",102,102,102)
blue =       Color("Blue",0,80,205)
white =      Color("White",255,255,255)
lightGray =  Color("Light Gray",170,170,170)
lightBlue =  Color("Light Blue",38,201,201)
green =      Color("Green",1,116,32)
brown =      Color("Brown",105,21,6)
lightBrown = Color("Light Brown",150,65,18)
lightGreen = Color("Light Green",17, 176, 60)
red =        Color("Red",255,0,19)
orange =     Color("Orange",255,120,41)
uglyBrown =  Color("Ugly Brown",176,112,28)
purple =     Color("Purple",153,0,78)
skin =       Color("Skin Color",203,90,87)
yellow =     Color("Yellow",255,193,38)
pink =       Color("Pink",255,0,143)
lightPink =  Color("Light Pink",254,175,168)

DEFAULT_COLORS=tuple((c.name,c.RGB) for c in allColors)

def reset_palette():
    allColors.clear()
    for name,rgb in DEFAULT_COLORS:Color(name,*rgb)
    from PixelData import closest_color
    closest_color.cache_clear()

from pathlib import Path

from RuntimePaths import atomic_write_text, data_dir, read_json, read_bounded_text

DATA_DIR = data_dir()
POSITIONS_FILE = DATA_DIR / "positions.txt"

# Match the existing profile-export and calibration-fingerprint byte budget.
# Palette files and their supported legacy files retain the same domain data.
MAX_CALIBRATION_BYTES = 8 * 1024 * 1024


def load_positions(path=POSITIONS_FILE):
    """Validate the entire legacy position file before changing any colors."""
    values = [int(line) for line in read_bounded_text(path,max_bytes=MAX_CALIBRATION_BYTES).splitlines()]
    if len(values) != len(allColors) * 2:
        raise ValueError(f"Position file must contain {len(allColors) * 2} coordinates. Recalibrate colors.")
    for index, color in enumerate(allColors):
        color.x, color.y = values[index * 2:index * 2 + 2]


def save_positions(path=POSITIONS_FILE):
    path = Path(path)
    atomic_write_text(path, "".join(f"{c.x}\n{c.y}\n" for c in allColors))


def enable_dpi_awareness():
    """Use physical screen coordinates consistently for capture and drawing."""
    from DpiSupport import enable_per_monitor_v2
    return enable_per_monitor_v2()


PALETTE_FILE = POSITIONS_FILE.with_name("palette.json")


def sample_screen_colors(points):
    """Read physical screen pixels through the bounded native sampling path."""
    from ScreenPixelSampling import sample_screen_colors as sample
    return sample(points)


def sample_screen_color(x, y):
    """Read one physical screen pixel, including multiple monitors."""
    return list(sample_screen_colors([(x,y)])[0])


def save_palette(rgb_values):
    import json
    rgb_values=[list(normalize_rgb(value)) for value in rgb_values]
    atomic_write_text(PALETTE_FILE, json.dumps(rgb_values))


def load_palette():
    if not PALETTE_FILE.exists():
        return
    values = read_json(PALETTE_FILE, max_bytes=MAX_CALIBRATION_BYTES)
    if not isinstance(values,list) or len(values)!=len(allColors):
        raise ValueError("Invalid palette.json. Recalibrate colors.")
    try:values=[normalize_rgb(rgb) for rgb in values]
    except ValueError as error:raise ValueError("Invalid palette.json. Recalibrate colors.") from error
    for color, rgb in zip(allColors, values):
        color.R, color.G, color.B = rgb
        color.RGB = tuple(rgb)
    from PixelData import closest_color
    closest_color.cache_clear()


CALIBRATION_FILE = DATA_DIR / 'calibration.json'


def validate_calibration(data, profile_key=None):
    """Validate calibration payload and return normalized rows.

    Version 4 adds an optional target-window anchor. Older versions remain
    readable for preview/migration, but Paint drawing can require an anchored
    calibration before any native input is armed.
    """
    if not isinstance(data,dict) or data.get('version') not in (1,2,3,4):
        raise ValueError('Invalid calibration. Recalibrate.')
    stored_profile=data.get('profile')
    if profile_key is not None and stored_profile not in (None,'',str(profile_key)):
        raise ValueError('Color calibration belongs to a different drawing profile.')
    state=str(data.get('state') or 'calibrated').strip().lower()
    if state not in ('unavailable','estimated','calibrated','verified'):
        raise ValueError('Invalid calibration state.')
    if data.get('version') == 4 and data.get('anchor') is not None:
        from CalibrationAnchors import validate_anchor
        validate_anchor(data['anchor'])
    rows=data.get('colors')
    if not isinstance(rows,list) or not 1<=len(rows)<=96:
        raise ValueError('Calibration must contain 1–96 colors.')
    positions=[];normalized=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not row['name']:
            raise ValueError('Incorrect color order in calibration.')
        values=row.get('position')
        if not isinstance(values,list) or len(values)!=2 or any(type(v) is not int for v in values):
            raise ValueError('Invalid coordinates or color values.')
        color_value=row.get('rgb',row.get('argb'))
        try:rgb=normalize_rgb(color_value)
        except (TypeError,ValueError):raise ValueError('Invalid RGB/ARGB color.') from None
        positions.append(tuple(row['position']))
        clean=dict(row);clean['rgb']=list(rgb);clean.pop('argb',None);normalized.append(clean)
    if len(set(positions))!=len(positions):raise ValueError('Duplicate color positions.')
    return normalized


def calibration_metadata(path=CALIBRATION_FILE, *, profile_key=None):
    """Return validated metadata without mutating the global palette."""
    path=Path(path)
    if not path.exists():
        return {'version':0,'anchor':None}
    data=read_json(path,max_bytes=MAX_CALIBRATION_BYTES)
    rows=validate_calibration(data, profile_key=profile_key)
    anchor=data.get('anchor') if data.get('version')==4 else None
    if anchor is not None:
        from CalibrationAnchors import validate_anchor
        anchor=validate_anchor(anchor)
    verification=data.get('verification') if isinstance(data.get('verification'),dict) else {}
    return {'version':data.get('version'), 'anchor':anchor, 'profile':data.get('profile'),
            'state':str(data.get('state') or 'calibrated').lower(), 'verification':dict(verification),
            'count':len(rows)}


def save_calibration(positions,rgbs,path=CALIBRATION_FILE,*,names=None,indices=None,anchor=None,
                     profile_key=None,state='calibrated',verification=None):
    import json
    if len(positions)!=len(rgbs):raise ValueError('Different numbers of colors and positions.')
    normalized=[normalize_rgb(rgb) for rgb in rgbs]
    state=str(state or 'calibrated').strip().lower()
    if state not in ('unavailable','estimated','calibrated','verified'):
        raise ValueError('Invalid calibration state.')
    data={'version':4,'colors':[{'name':f'Color {i+1}','position':list(map(int,p)),'rgb':list(rgb)}
          for i,(p,rgb) in enumerate(zip(positions,normalized))], 'state':state}
    if profile_key is not None:data['profile']=str(profile_key)
    if verification is not None:
        if not isinstance(verification,dict):raise ValueError('Calibration verification metadata must be a dictionary.')
        data['verification']=dict(verification)
    if anchor is not None:
        from CalibrationAnchors import validate_anchor
        data['anchor']=validate_anchor(anchor)
    if names is not None:
        if len(names)!=len(rgbs):raise ValueError('Incorrect number of color names.')
        for row,name in zip(data['colors'],names):row['name']=name
    if indices is not None:
        if len(indices)!=len(rgbs) or indices!=list(range(len(rgbs))):raise ValueError('Invalid color index map.')
        for row,index in zip(data['colors'],indices):row['game_index']=index
    validate_calibration(data, profile_key=profile_key)
    atomic_write_text(Path(path),json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))


def load_calibration(path=CALIBRATION_FILE,*,current_client_rect=None,require_anchor=False,profile_key=None):
    """Load colors and optionally translate saved points to a moved window.

    Resizing is rejected by CalibrationAnchors because Paint may reflow its
    toolbar/palette.  This happens before any mouse input is armed.
    """
    path=Path(path);anchor=None
    if not path.exists():
        if path!=CALIBRATION_FILE:raise FileNotFoundError(path)
        old=[(c.x,c.y,c.RGB) for c in allColors]
        try:
            load_positions();load_palette()
            data={'version':1,'colors':[{'name':c.name,'position':[c.x,c.y],'rgb':list(c.RGB)} for c in allColors]}
            rows=validate_calibration(data, profile_key=profile_key)
        finally:
            for c,(x,y,rgb) in zip(allColors,old):c.x,c.y=x,y;c.RGB=rgb;c.R,c.G,c.B=rgb
    else:
        data=read_json(path,max_bytes=MAX_CALIBRATION_BYTES)
        rows=validate_calibration(data, profile_key=profile_key)
        if data.get('version')==4 and data.get('anchor') is not None:
            from CalibrationAnchors import validate_anchor
            anchor=validate_anchor(data['anchor'])
    if require_anchor and anchor is None:
        raise ValueError('This color calibration uses fixed screen coordinates. Recalibrate colors once in the current Image Draw Bot version before drawing.')
    positions=[tuple(row['position']) for row in rows]
    if current_client_rect is not None and anchor is not None:
        from CalibrationAnchors import resolve_points
        positions=resolve_points(positions,anchor,current_client_rect)
    allColors.clear()
    for row,position in zip(rows,positions):
        c=Color(row['name'],*row['rgb']);c.x,c.y=position
    from PixelData import closest_color
    closest_color.cache_clear()
    return {'anchor':anchor,'count':len(rows)}
