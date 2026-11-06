"""Local-only privacy helpers used by diagnostics.

No telemetry or network reporting is implemented here. This module only removes
common local identifiers/secrets from text before a diagnostics ZIP is created.
"""
from __future__ import annotations
from pathlib import Path
import json
import math
import re


# Apostrophes are valid in prepared URL paths and query values. A quote must
# not terminate matching early and leave the remainder of a signed link intact.
_URL_RE = re.compile(r'''(?i)\bhttps?://[^\s<>"]+''')
_RELATIVE_URL_RE = re.compile(r'''(?i)(\burl["']?\s*[:=]\s*["']?)(/[^\s<>"]+)''')
_AUTHORIZATION_RE = re.compile(
    r'''(?im)((?<![\w-])(?:proxy-)?authorization["']?\s*[:=]\s*)'''
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n]+)'''
)
_CREDENTIAL_RE = re.compile(
    r'''(?i)((?:api[_-]?key|token|password|passwd|secret)["']?\s*[:=]\s*)'''
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)'''
)
_COOKIE_RE = re.compile(
    r'''(?im)((?<![\w-])(?:set-cookie|cookie)["']?\s*[:=]\s*)'''
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n]+)'''
)
# JSON and repr escape Windows separators and may encode a Unicode username.
# Keep those escape sequences inside the username being removed, while leaving
# the original separators and the surrounding serialized document intact.
_WINDOWS_HOME_RE = re.compile(
    r'''(?i)([a-z]:(?:\\+|/)Users(?:\\+|/))'''
    r'''(?:\\+(?:u[0-9a-f]{4}|U[0-9a-f]{8}|x[0-9a-f]{2}|')|[^\\/\r\n"<>])+'''
)
_POSIX_HOME_RE = re.compile(r'(/(?:home|Users)/)[^/\r\n"<>]+')
# Escaped quotes cannot begin another literal. Without this guard a malformed
# line containing thousands of escaped quotes is rescanned quadratically.
_QUOTED_TEXT_RE = re.compile(r'''(?<!\\)(?P<quote>["'])(?:\\.|(?!(?P=quote))[^\\\r\n])*(?P=quote)''')


def _redact_profile_paths(text):
    text = _WINDOWS_HOME_RE.sub(r'\1<user>', text)
    return _POSIX_HOME_RE.sub(r'\1<user>', text)


def _redact_quoted_profile_paths(match):
    value = match.group(0)
    # Redact inside the literal's own boundaries first. This keeps a bare home
    # followed by a closing apostrophe from consuming later repr arguments,
    # without treating a real apostrophe inside a username as a delimiter.
    return value[0] + _redact_profile_paths(value[1:-1]) + value[-1]


def _redact_url_value(original):
    # Keep error-message punctuation without retaining any query/fragment data.
    url = original.rstrip(".,;)]}'")
    suffix = original[len(url):]
    url = re.sub(r'(?i)(https?://)[^/?#]*@', r'\1<redacted>@', url)
    # Signed links can use arbitrary parameter names. Preserve the host/path
    # needed for debugging, but never export query values or fragment tokens.
    url = re.sub(r'([?#]).*', r'\1<redacted>', url, count=1)
    return url + suffix


def _redact_credential(match):
    value = match.group(2)
    quote = value[0] if value[:1] in ('"', "'") and value[-1:] == value[:1] else ''
    return match.group(1) + quote + '<redacted>' + quote


def _redact_authorization(match):
    value = match.group(2)
    quote = value[0] if value[:1] in ('"', "'") and value[-1:] == value[:1] else ''
    body = value[1:-1] if quote else value
    scheme = body.split(None, 1)[0] if body.strip() else ''
    prefix = scheme + ' ' if scheme.lower() in ('basic', 'bearer') else ''
    return match.group(1) + quote + prefix + '<redacted>' + quote


def sanitize_text(text: str) -> str:
    # Redact URLs before inserting home-path placeholders: '<USER_HOME>' would
    # otherwise terminate URL matching before a following signed query string.
    text = _URL_RE.sub(lambda match: _redact_url_value(match.group(0)), str(text))
    # urllib3 connection failures often include only the relative request target,
    # e.g. "Max retries exceeded with url: /image.png?signature=...".
    text = _RELATIVE_URL_RE.sub(
        lambda match: match.group(1) + _redact_url_value(match.group(2)), text
    )
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        home = ''
    if home:
        for variant in (home, home.replace("\\", "/")):
            for spelling in (variant, json.dumps(variant)[1:-1], repr(variant)[1:-1]):
                text = text.replace(spelling, "<USER_HOME>")
    text = _QUOTED_TEXT_RE.sub(_redact_quoted_profile_paths, text)
    text = _redact_profile_paths(text)
    text = _AUTHORIZATION_RE.sub(_redact_authorization, text)
    text = _COOKIE_RE.sub(_redact_credential, text)
    text = _CREDENTIAL_RE.sub(_redact_credential, text)
    return text


def safe_context(context: object) -> dict:
    """Bound primitive diagnostics context; never accepts paths/coordinates."""
    if not isinstance(context, dict):
        return {}
    allowed = {
        'profile','activity','quality','speed','precision','render_style','draw_quality','human_mode',
        'gpu_mode','gpu_vram','gpu_performance','background_fill','fill_engine',
        'background_simplification','color_grouping','color_workflow','stroke_optimizer','adaptive_detail',
        'visual_verification','color_rendering','color_layers','custom_color_workflow','tool_strategy',
        'cpu_workers','cpu_engine','ram_budget','resource_scheduler','drawing_mode','shape_model',
        'time_budget_mode','target_stroke_count','paint_single_color','paint_tool','brush_px',
        'time_limit_seconds','palette_ready','drawing_area_selected','target_lock_valid',
    }
    cleaned={}
    for key in allowed:
        if key not in context:
            continue
        value=context[key]
        if type(value) is float and not math.isfinite(value):
            continue
        if isinstance(value,bool) or type(value) in (int,float):
            cleaned[key]=value
        elif isinstance(value,str):
            cleaned[key]=sanitize_text(value)[:200]
    return cleaned
