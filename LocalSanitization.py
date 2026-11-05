"""Local-only privacy helpers used by diagnostics.

No telemetry or network reporting is implemented here. This module only removes
common local identifiers/secrets from text before a diagnostics ZIP is created.
"""
from __future__ import annotations
from pathlib import Path
import re


# Apostrophes are valid in prepared URL paths and query values. A quote must
# not terminate matching early and leave the remainder of a signed link intact.
_URL_RE = re.compile(r'''(?i)\bhttps?://[^\s<>"]+''')
_RELATIVE_URL_RE = re.compile(r'''(?i)(\burl["']?\s*[:=]\s*["']?)(/[^\s<>"]+)''')
_AUTHORIZATION_RE = re.compile(
    r'''(?i)((?:proxy-)?authorization["']?\s*[:=]\s*["']?(?:bearer|basic)\s+)[^\s"',;}\]]+'''
)
_CREDENTIAL_RE = re.compile(
    r'''(?i)((?:api[_-]?key|token|password|passwd|secret)["']?\s*[:=]\s*)'''
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)'''
)


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


def sanitize_text(text: str) -> str:
    # Redact URLs before inserting home-path placeholders: '<USER_HOME>' would
    # otherwise terminate URL matching before a following signed query string.
    text = _URL_RE.sub(lambda match: _redact_url_value(match.group(0)), str(text))
    # urllib3 connection failures often include only the relative request target,
    # e.g. "Max retries exceeded with url: /image.png?signature=...".
    text = _RELATIVE_URL_RE.sub(
        lambda match: match.group(1) + _redact_url_value(match.group(2)), text
    )
    home = str(Path.home())
    if home:
        text = text.replace(home, "<USER_HOME>")
        text = text.replace(home.replace("\\", "/"), "<USER_HOME>")
    text = re.sub(r"(?i)C:\\Users\\[^\\\r\n]+", r"C:\\Users\\<user>", text)
    text = re.sub(r"(?i)C:/Users/[^/\r\n]+", r"C:/Users/<user>", text)
    text = _AUTHORIZATION_RE.sub(r'\1<redacted>', text)
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
        if isinstance(value,bool) or type(value) in (int,float):
            cleaned[key]=value
        elif isinstance(value,str):
            cleaned[key]=sanitize_text(value)[:200]
    return cleaned
