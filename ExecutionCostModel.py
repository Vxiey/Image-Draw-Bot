"""Calibrated execution-cost model for Image Draw Bot v1.0.132-beta.

The model estimates wall-clock *input* cost, not image-processing cost.  It
reuses StrokeDelivery's profile-specific native spacing and DrawTimeCalibration's
profile-local measurements.  No mouse input is sent here.

Costs deliberately include cursor travel, press/release settle, sampled drag
moves, palette/tool/brush changes and verification.  Learned values are used
only when the exact profile/tool/brush/color-workflow calibration contains them;
otherwise conservative deterministic defaults remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any, Iterable, Sequence

from DrawTimeCalibration import correction_for
from SpeedOptimizer import normalize_speed, phase_delay
from StrokeDelivery import resolve_stroke_delivery
from Precision import effective_step, precision_path_count, round_screen

Point = tuple[int, int]
EXECUTION_MODEL_VERSION = 6


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def _path_length(path: Sequence[Point], sx: float = 1.0, sy: float = 1.0) -> float:
    if len(path) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(path, path[1:]):
        total += math.hypot((float(b[0])-float(a[0]))*sx,
                            (float(b[1])-float(a[1]))*sy)
    return total


def _operation_type(path: Sequence[Point], scaled_length: float) -> str:
    if len(path) <= 1:
        return "dot"
    closed = len(path) >= 4 and path[0] == path[-1]
    if closed:
        return "outline"
    return "short_stroke" if scaled_length <= 28.0 else "long_stroke"


@dataclass(frozen=True)
class CostBreakdown:
    total_seconds: float
    drag_seconds: float = 0.0
    travel_seconds: float = 0.0
    press_release_seconds: float = 0.0
    palette_seconds: float = 0.0
    custom_color_seconds: float = 0.0
    tool_seconds: float = 0.0
    brush_seconds: float = 0.0
    fill_seconds: float = 0.0
    verification_seconds: float = 0.0
    target_processing_seconds: float = 0.0
    operations: int = 0
    moves: int = 0
    palette_switches: int = 0
    custom_color_switches: int = 0
    custom_selection_seconds: float = 0.0
    color_verifications: int = 0
    tool_switches: int = 0
    brush_switches: int = 0
    source: str = "deterministic profile model"

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key, value in tuple(out.items()):
            if isinstance(value, float):
                out[key] = round(value, 6)
        return out


class ExecutionCostModel:
    """Stateful candidate/sequence cost estimator in target-canvas pixels."""

    def __init__(self, options: dict[str, Any], source_size: tuple[int, int],
                 fitted_size: tuple[int, int]):
        self.options = dict(options or {})
        self.source_size = (max(1, int(source_size[0])), max(1, int(source_size[1])))
        self.fitted_size = (max(1, int(fitted_size[0])), max(1, int(fitted_size[1])))
        _sx_default = self.fitted_size[0] / self.source_size[0]
        _sy_default = self.fitted_size[1] / self.source_size[1]
        self.sx = max(.001, _safe_float(self.options.get("_execution_scale_x", self.options.get("_hybrid_scale_x", _sx_default)), _sx_default))
        self.sy = max(.001, _safe_float(self.options.get("_execution_scale_y", self.options.get("_hybrid_scale_y", _sy_default)), _sy_default))
        self.delivery = resolve_stroke_delivery(self.options, dry_run=False)
        self.precision = self.options.get("precision", "High")
        self.step_px = effective_step(self.precision, self.delivery.step_px)
        self.speed = normalize_speed(self.options.get("speed", "Balanced"))
        self.delay = max(0.0, _safe_float(self.options.get("delay"), 0.0))
        self.path_wait = max(float(self.delivery.min_path_delay),
                             float(phase_delay(self.delay, self.speed, "path")))
        self.travel_wait = max(.0005, float(phase_delay(self.delay, self.speed, "travel")))
        self.boundary_wait = max(.0005, float(phase_delay(self.delay, self.speed, "boundary")))
        _override = self.options.get("_execution_cost_calibration_override")
        self.calibration = dict(_override) if isinstance(_override, dict) else correction_for(self.options)
        self.runtime = dict(self.calibration.get("operation_runtime") or {})
        self.samples = max(0, int(self.calibration.get("samples") or 0))
        learned_ratio = max(.55, min(4.0, _safe_float(self.calibration.get("ratio"), 1.0)))
        self.multiplier = learned_ratio if self.samples >= 3 else (
            max(1.08, learned_ratio) if self.samples == 2 else
            max(1.16, learned_ratio) if self.samples == 1 else 1.0
        )
        self.source = ("measured local calibration" if self.samples >= 3 else
                       f"learning local calibration ({self.samples}/3)" if self.samples else
                       "deterministic profile model")
        from AdaptiveBrushEngine import verified_brush_sizes
        sizes,dynamic=verified_brush_sizes(str(self.options.get('profile_key') or ''),
            self.options.get('browser_brush_plan'),max(1,int(self.options.get('brush_px') or 1)))
        self._color_reset_brushes=frozenset(sizes) if dynamic else frozenset()

    def _learned_average(self, kind: str, fallback: float) -> float:
        aliases = {
            "dot": ("dot", "point"),
            "short_stroke": ("short_stroke", "stroke", "path", "drag"),
            "long_stroke": ("long_stroke", "stroke", "path", "drag"),
            "outline": ("outline", "stroke", "path", "drag"),
            "palette_change": ("palette_change", "color_change"),
            "tool_change": ("tool_change",),
            "brush_change": ("brush_change", "tool_change"),
            "fill": ("fill", "fill_action", "bucket_fill"),
            "verification": ("verification", "visual_verify"),
        }
        for name in aliases.get(str(kind),(str(kind),)):
            item = self.runtime.get(name)
            if not isinstance(item, dict):
                continue
            avg = _safe_float(item.get("average_seconds"), 0.0)
            if avg <= 0.0:
                count=max(0,int(item.get("count") or item.get("observations") or 0))
                total=max(0.0,_safe_float(item.get("total_seconds"),0.0))
                avg=total/count if count else 0.0
            if avg > 0.0:
                return avg
        return fallback



    @property
    def scale_x(self) -> float:
        return float(self.sx)

    @property
    def scale_y(self) -> float:
        return float(self.sy)

    @property
    def path_fixed_seconds(self) -> float:
        base=(self.travel_wait + float(self.delivery.press_settle) +
              float(self.delivery.release_settle) + self.boundary_wait + .0015)
        return max(.000001,base*self.multiplier)

    @property
    def learned_path_floor_seconds(self) -> float:
        values=[]
        for kind in ("short_stroke","long_stroke","stroke","path"):
            value=self._learned_average(kind,0.0)
            if value>0:values.append(float(value))
        return max(0.0,min(values)*self.multiplier) if values else 0.0

    @property
    def draw_seconds_per_px(self) -> float:
        return max(1e-12,(self.path_wait/self.step_px)*self.multiplier)

    @property
    def color_change_seconds(self) -> float:
        return float(self.switch_cost("palette_change"))

    @property
    def model_version(self) -> int:
        return EXECUTION_MODEL_VERSION

    @property
    def calibration_confidence(self) -> float:
        if self.samples<=0:return 0.0
        return max(0.0,min(.95,1.0-math.exp(-float(self.samples)/4.0)))

    @property
    def uncertainty_multiplier(self) -> float:
        if self.samples<=0:return 1.0
        return 1.0+(1.0-self.calibration_confidence)*.10

    def path_seconds(self,path: Sequence[Point],*,cursor: Point|None=None,brush_px: int|None=None) -> float:
        return float(self.path_cost(path,cursor=cursor,brush_px=brush_px).total_seconds)

    def paths_seconds(self,paths: Iterable[Sequence[Point]],*,cursor: Point|None=None,brush_px: int|None=None) -> float:
        total=0.0;current=cursor
        for path in paths or ():
            if not path:continue
            total+=self.path_seconds(path,cursor=current,brush_px=brush_px)
            current=tuple(map(int,path[-1]))
        return total

    def risk_adjusted_seconds(self,seconds: float) -> float:
        value=max(0.0,float(seconds or 0.0))
        return value*self.uncertainty_multiplier

    def as_dict(self) -> dict[str,Any]:
        return {
            "model":"ExecutionCostModel","model_version":self.model_version,"source":self.source,
            "samples":self.samples,"scale_x":round(self.scale_x,7),"scale_y":round(self.scale_y,7),
            "path_fixed_seconds":round(self.path_fixed_seconds,7),
            "draw_seconds_per_px":round(self.draw_seconds_per_px,9),
            "color_change_seconds":round(self.color_change_seconds,7),
            "calibration_confidence":round(self.calibration_confidence,7),
            "uncertainty_multiplier":round(self.uncertainty_multiplier,7),
        }

    def path_cost(self, path: Sequence[Point], *, cursor: Point | None = None,
                  brush_px: int | None = None) -> CostBreakdown:
        path = tuple((int(p[0]), int(p[1])) for p in (path or ()))
        if not path:
            return CostBreakdown(0.0, source=self.source)
        _brush = max(1, int(brush_px or self.options.get("brush_px") or 1))
        length = _path_length(path, self.sx, self.sy)
        start = path[0]
        travel_px = 0.0
        if cursor is not None:
            travel_px = math.hypot((start[0]-cursor[0])*self.sx,
                                   (start[1]-cursor[1])*self.sy)
        # Keep the historic bounded distance curve, but never hide it inside a
        # learned operation average. A learned average is the zero-distance /
        # nominal-travel baseline; actual cursor distance is added afterwards.
        travel_base = self.travel_wait
        travel_distance = min(.10, travel_px * .000045)
        press_release = float(self.delivery.press_settle + self.delivery.release_settle)

        if len(path) <= 1:
            body = press_release + max(.012, self.boundary_wait)
            learned = self._learned_average("dot", 0.0)
            if learned > 0.0:
                learned_body=max(.001,learned-travel_base)
                total=travel_base+travel_distance+learned_body
                body_scale=learned_body/max(.000001,body)
                travel_seconds=travel_base+travel_distance
            else:
                total=(travel_base+travel_distance+body)*self.multiplier
                body_scale=self.multiplier
                travel_seconds=(travel_base+travel_distance)*self.multiplier
            return CostBreakdown(total, travel_seconds=travel_seconds,
                                 press_release_seconds=press_release*body_scale,
                                 target_processing_seconds=max(.012,self.boundary_wait)*body_scale,
                                 operations=1, moves=1, source=self.source)

        moves = 0
        # Native delivery first maps source pixel centres to integer desktop
        # pixels, then applies the selected precision cap and de-duplicates
        # repeated positions. Count that same path without allocating it.
        screen_path = [(round_screen((x + .5) * self.sx - .5),
                        round_screen((y + .5) * self.sy - .5)) for x, y in path]
        for a, b in zip(screen_path, screen_path[1:]):
            moves += precision_path_count(a, b, self.precision, self.delivery.step_px)
        drag = moves * self.path_wait
        target = self.boundary_wait + .0015
        body = press_release + drag + target
        kind = _operation_type(path, length)
        learned = self._learned_average(kind, 0.0)
        if learned > 0.0:
            learned_body=max(.001,learned-travel_base)
            total=travel_base+travel_distance+learned_body
            body_scale=learned_body/max(.000001,body)
            travel_seconds=travel_base+travel_distance
        else:
            total=(travel_base+travel_distance+body)*self.multiplier
            body_scale=self.multiplier
            travel_seconds=(travel_base+travel_distance)*self.multiplier
        return CostBreakdown(
            total, drag_seconds=drag*body_scale, travel_seconds=travel_seconds,
            press_release_seconds=press_release*body_scale,
            target_processing_seconds=target*body_scale, operations=1, moves=moves,
            source=self.source)

    def switch_cost(self, kind: str) -> float:
        kind = str(kind)
        defaults = {
            "palette_change": float(self.delivery.palette_click_delay),
            "tool_change": float(self.delivery.ui_control_delay),
            "brush_change": max(.06, float(self.delivery.ui_control_delay) * .75),
            "fill": max(.12, float(self.delivery.ui_control_delay) + .04),
            "verification": max(.08, float(self.delivery.palette_click_delay) * .45),
        }
        base = defaults.get(kind, .0)
        learned = self._learned_average(kind, 0.0)
        return learned if learned > 0.0 else base * self.multiplier

    def is_custom_color(self, color_index: int | None) -> bool:
        selectors = self.options.get('color_selectors') or ()
        selector = (selectors[color_index] if color_index is not None
                    and 0 <= color_index < len(selectors) else None)
        return bool(not self.options.get('paint_current_color')
                    and self.options.get('exact_color_available')
                    and isinstance(selector, dict) and selector.get('kind') == 'custom')

    def color_selection_cost(self, color_index: int | None) -> tuple[float,float]:
        """Palette/custom portions of one actual selection, including learned UI time.

        Runtime records a complete non-palette select() call as color_change,
        before verification or drawing. Such a measurement must replace the
        complete default selection, not receive another custom-dialog surcharge.
        """
        if self.options.get('paint_current_color'):
            return 0.0,0.0
        palette=self.switch_cost('palette_change')
        if not self.is_custom_color(color_index):return palette,0.0
        learned=self._learned_average('color_change',0.0)
        if learned>0:
            # Keep the diagnostic split nonnegative even when a learned custom
            # selector is faster than the palette default or historical average.
            palette=min(palette,learned)
            return palette,learned-palette
        return palette,.78*self.multiplier

    def brush_resets_color(self, previous: int | None, requested: int) -> bool:
        return previous is not None and previous!=requested and requested in self._color_reset_brushes

    def sequence_cost(self, sequence: Iterable[dict[str, Any]], *,
                      initial_cursor: Point | None = None,
                      initial_color: int | None = None,
                      initial_brush: int | None = None,
                      include_color_verification: bool = False,
                      include_geometry: bool = True,
                      cancelled=None) -> CostBreakdown:
        cursor = initial_cursor
        color = initial_color
        brush = initial_brush
        phase = None
        verified_colors = set()
        totals = {
            "drag": 0.0, "travel": 0.0, "press": 0.0, "palette": 0.0, "custom": 0.0,
            "tool": 0.0, "brush": 0.0, "fill": 0.0, "verification": 0.0,
            "target": 0.0, "ops": 0, "moves": 0, "palette_n": 0,
            "tool_n": 0, "brush_n": 0, "custom_n": 0, "custom_selection": 0.0,
        }
        for raw in sequence or ():
            if cancelled is not None and cancelled():
                raise InterruptedError()
            entry = dict(raw)
            operation = str(entry.get("operation_type") or "stroke")
            if operation in ("fill", "fill_action"):
                totals["fill"] += self.switch_cost("fill"); totals["ops"] += 1
                continue
            if operation == "verification":
                totals["verification"] += self.switch_cost("verification"); totals["ops"] += 1
                continue
            if operation == "tool_change":
                totals["tool"] += self.switch_cost("tool_change"); totals["tool_n"] += 1; totals["ops"] += 1
                continue
            if operation == "palette_change":
                selected_color=int(entry['color_index']) if entry.get('color_index') is not None else color
                palette,custom=self.color_selection_cost(selected_color)
                totals["palette"] += palette; totals["custom"] += custom
                totals["palette_n"] += 1; totals["ops"] += 1
                if self.is_custom_color(selected_color):
                    totals['custom_n'] += 1
                    totals['custom_selection'] += palette + custom
                if entry.get("color_index") is not None:
                    color = int(entry.get("color_index"))
                continue
            if operation == "brush_change":
                totals["brush"] += self.switch_cost("brush_change"); totals["brush_n"] += 1; totals["ops"] += 1
                if entry.get("brush_px") is not None:
                    requested=max(1,int(entry.get('brush_px')))
                    if self.brush_resets_color(brush,requested):color=None
                    brush=requested
                continue
            path = entry.get("path") or ()
            if not path:
                continue
            new_color = int(entry.get("color_index", color if color is not None else 0))
            new_brush = max(1, int(entry.get("brush_px") or brush or self.options.get("brush_px") or 1))
            new_phase=str(entry.get('phase','details'))
            if (phase is not None and new_phase!=phase) or self.brush_resets_color(brush,new_brush):
                color=None
            if new_color!=color and not self.options.get('paint_current_color'):
                palette,custom=self.color_selection_cost(new_color)
                totals['palette']+=palette;totals['custom']+=custom;totals['palette_n']+=1
                if self.is_custom_color(new_color):
                    totals['custom_n'] += 1
                    totals['custom_selection'] += palette + custom
            if (include_color_verification and self.options.get('adaptive_color_verification')
                    and not self.options.get('paint_current_color') and new_color not in verified_colors):
                totals['verification']+=self.switch_cost('verification')
                verified_colors.add(new_color)
            if brush is not None and new_brush != brush:
                totals["brush"] += self.switch_cost("brush_change"); totals["brush_n"] += 1
            if include_geometry:
                piece = self.path_cost(path, cursor=cursor, brush_px=new_brush)
                totals["drag"] += piece.drag_seconds
                totals["travel"] += piece.travel_seconds
                totals["press"] += piece.press_release_seconds
                totals["target"] += piece.target_processing_seconds
                totals["ops"] += piece.operations
                totals["moves"] += piece.moves
            path = entry.get("path") or ()
            if path:
                cursor = tuple(map(int, path[-1]))
            color = new_color
            brush = new_brush
            phase = new_phase
        total = sum(totals[k] for k in ("drag","travel","press","palette","custom","tool","brush","fill","verification","target"))
        return CostBreakdown(
            total_seconds=total, drag_seconds=totals["drag"],
            travel_seconds=totals["travel"], press_release_seconds=totals["press"],
            palette_seconds=totals["palette"], tool_seconds=totals["tool"],
            custom_color_seconds=totals['custom'],
            brush_seconds=totals["brush"], fill_seconds=totals["fill"],
            verification_seconds=totals["verification"],
            target_processing_seconds=totals["target"], operations=totals["ops"],
            moves=totals["moves"], palette_switches=totals["palette_n"],
            custom_color_switches=totals['custom_n'],
            custom_selection_seconds=totals['custom_selection'],
            color_verifications=len(verified_colors),
            tool_switches=totals["tool_n"], brush_switches=totals["brush_n"],
            source=self.source)

    def fixed_overhead(self, *, active_colors: int = 0, fill_actions: int = 0,
                       include_countdown: bool = True) -> CostBreakdown:
        palette_n = 0 if self.options.get("paint_current_color") else max(0, int(active_colors))
        tool_n = len(self.options.get("tool_actions") or ())
        verification_n = (palette_n if self.options.get("adaptive_color_verification") else 0)
        palette = palette_n * self.switch_cost("palette_change")
        tool = tool_n * self.switch_cost("tool_change")
        fill = max(0, int(fill_actions)) * self.switch_cost("fill")
        verification = verification_n * self.switch_cost("verification")
        countdown = 3.0 if include_countdown else 0.0
        focus = 0.0 if self.options.get("paint_profile") or str(self.options.get("profile_key")) == "microsoft-paint" else .35
        total = countdown + focus + palette + tool + fill + verification
        return CostBreakdown(
            total_seconds=total, palette_seconds=palette, tool_seconds=tool,
            fill_seconds=fill, verification_seconds=verification,
            target_processing_seconds=countdown+focus, operations=palette_n+tool_n+fill_actions+verification_n,
            palette_switches=palette_n, tool_switches=tool_n, source=self.source)


def build_cost_model(options: dict[str, Any], source_size: tuple[int, int],
                     fitted_size: tuple[int, int]) -> ExecutionCostModel:
    return ExecutionCostModel(options, source_size, fitted_size)
