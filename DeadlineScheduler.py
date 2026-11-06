"""Live deadline scheduler for Image Draw Bot Step 8.

The planning pass already chooses a safe, high-value subset of the drawing.  This
module is the *runtime* guard that keeps that plan honest while the mouse is
actually drawing.  It continuously compares remaining render budget with the
observed execution rate and progressively changes policy:

    NORMAL -> CATCH_UP -> PANIC

NORMAL executes the planned quality pass.  CATCH_UP trims low-value accuracy and
cleanup work before the renderer is late.  PANIC becomes structure-first and
only spends scarce time on major coverage, silhouettes and exceptionally
important details.  The hard render budget is never intentionally crossed; the
game-timer reserve is owned by TimeBudgetEngine and therefore remains untouched.

The scheduler never invents geometry, changes RGB values or bypasses canvas
safety.  Extra Fast 2.0 has already produced the longest safe connected paths at
planning time, so runtime strategy switching is deliberately a scheduling
policy change rather than an unsafe mid-stroke geometry rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque
import math
from typing import Any


NORMAL = "NORMAL"
CATCH_UP = "CATCH_UP"
PANIC = "PANIC"
DRAWING_OPERATIONS = frozenset(("stroke", "dot", "short_stroke", "long_stroke", "outline"))

# Centralized thresholds.  Keeping these in one place makes future profile
# tuning/test coverage straightforward and prevents magic numbers in DrawBot.
RUNTIME_POLICY = {
    "catch_up_fit_ratio": 0.88,
    "panic_fit_ratio": 1.05,
    "structural_gate": 0.75,
    "panic_detail_min_importance": 0.82,
    "panic_detail_min_structure": 0.82,
    "catchup_accuracy_min_importance": 0.62,
    "catchup_correction_min_importance": 0.76,
    "hard_stop_guard_seconds": 0.20,
    "sample_ratio_min": 0.25,
    "sample_ratio_max": 6.0,
    "ema_alpha": 0.28,
}


@dataclass
class SchedulerDecision:
    execute: bool
    panic: bool
    reason: str
    mode: str = NORMAL
    schedule_delta_seconds: float = 0.0
    structural_coverage: float = 1.0
    strategy: str = "planned-quality"
    predicted_remaining_seconds: float = 0.0
    runtime_cost_multiplier: float = 1.0


class DeadlineScheduler:
    """Deadline-aware runtime controller with live speed learning.

    ``estimated_cost_seconds`` remains the stable planning cost.  Runtime samples
    learn a bounded multiplier from real elapsed time instead of mutating the
    plan.  Future work is projected per operation type when enough samples are
    available, otherwise by a global EMA.  This makes the ETA react to a slow
    browser/Paint session within a few paths while remaining deterministic.
    """

    def __init__(self, sequence, *, start_time: float, budget_seconds: float | None, clock):
        self.sequence = [dict(entry) for entry in (sequence or ())]
        self.start_time = float(start_time)
        self.budget_seconds = None if budget_seconds is None else float(budget_seconds)
        if not math.isfinite(self.start_time) or (self.budget_seconds is not None and (not math.isfinite(self.budget_seconds) or self.budget_seconds <= 0)):
            raise ValueError("Scheduler start and budget must be finite; budget must be positive.")
        self.clock = clock

        self._remaining_by_type: dict[str, float] = defaultdict(float)
        for entry in self.sequence:
            self._remaining_by_type[self._op_type(entry)] += self._cost(entry)
        self._remaining_raw = sum(self._remaining_by_type.values())
        # Public compatibility field; from Step 8 onward it is the *live*
        # predicted cost rather than the original static planning sum.
        self.remaining_cost = self._remaining_raw

        self.skipped = 0
        self.skipped_low_value = 0
        self.executed = 0
        self.panic_activations = 0
        self.catch_up_activations = 0
        self.mode = NORMAL
        self.panic = False
        self._last_mode = NORMAL
        self._last_before = None
        self._last_entry_cost = 0.0
        self._last_entry_type = "stroke"
        self._actual_active_seconds = 0.0
        self._estimated_executed_seconds = 0.0
        self._global_ratio_ema = 1.0
        self._global_samples = 0
        self._type_ratio_ema: dict[str, float] = {}
        self._type_samples: dict[str, int] = defaultdict(int)
        self._recent_ratios = deque(maxlen=12)
        self._last_actual_seconds = 0.0
        self._last_predicted_seconds = self._remaining_raw
        self._recovered_from_catchup = 0
        self.replan_count = 0
        self.reordered_paths = 0
        self.replan_rejected_switch_cost = 0
        self._last_replan_sample = -1
        self._last_replan_mode = NORMAL
        self._last_replan_scale = 1.0
        self.current_phase = ""
        self.current_strategy = "planned-quality"
        self.phase_executed: dict[str, int] = defaultdict(int)
        self.phase_skipped: dict[str, int] = defaultdict(int)
        self.skip_reasons: dict[str, int] = defaultdict(int)

        self.structural_total = sum(self._structural_weight(e) for e in self.sequence if self._is_structural(e))
        self.structural_done = 0.0

    @staticmethod
    def _cost(entry: dict[str, Any]) -> float:
        try:
            value = float(entry.get("estimated_cost_seconds", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Invalid operation cost.") from error
        if not math.isfinite(value) or value < 0:
            raise ValueError("Operation cost must be finite and non-negative.")
        return value

    @staticmethod
    def _op_type(entry: dict[str, Any]) -> str:
        return str(entry.get("operation_type") or "stroke")

    @classmethod
    def _is_drawing(cls, entry: dict[str, Any]) -> bool:
        return cls._op_type(entry) in DRAWING_OPERATIONS

    @staticmethod
    def _phase(entry):
        return str(entry.get("deadline_phase") or entry.get("phase") or "accuracy")

    @classmethod
    def _is_structural(cls, entry):
        return cls._phase(entry) in ("major_coverage", "structure")

    @staticmethod
    def _score(entry, key, default):
        try:
            value = float(entry.get(key, default))
        except (TypeError, ValueError, OverflowError):
            return default
        return max(0.0, min(1.0, value)) if math.isfinite(value) else default

    @classmethod
    def _structural_weight(cls, entry):
        score = cls._score(entry, "structural_score", 0.0)
        imp = cls._score(entry, "importance", .5)
        return max(.05, score * .72 + imp * .28)

    def structural_coverage(self):
        if self.structural_total <= 1e-9:
            return 1.0
        return max(0.0, min(1.0, self.structural_done / self.structural_total))

    def _now(self):
        now = float(self.clock())
        if not math.isfinite(now):
            raise ValueError("Scheduler clock returned a non-finite timestamp.")
        return now

    def elapsed(self):
        return max(0.0, self._now() - self.start_time)

    def remaining_time(self):
        if self.budget_seconds is None:
            return float("inf")
        return max(0.0, self.budget_seconds - self.elapsed())

    def _runtime_scale(self, operation_type: str | None = None) -> float:
        """Return the bounded live cost multiplier for future work."""
        global_scale = self._global_ratio_ema if self._global_samples else 1.0
        if operation_type and self._type_samples.get(operation_type, 0) >= 2:
            typed = self._type_ratio_ema.get(operation_type, global_scale)
            # Blend typed and global timing so one noisy dot/outline sample does
            # not dominate a deadline decision.
            return max(.45, min(4.5, typed * .72 + global_scale * .28))
        return max(.45, min(4.5, global_scale))

    def predicted_remaining(self) -> float:
        predicted = 0.0
        for op_type, raw in self._remaining_by_type.items():
            if raw > 0:
                predicted += raw * self._runtime_scale(op_type)
        # Add a tiny, bounded variance guard once live samples exist.  This
        # reacts to jitter without double-counting TimeBudgetEngine's outer
        # safety reserve.
        if len(self._recent_ratios) >= 3 and predicted > 0:
            mean = sum(self._recent_ratios) / len(self._recent_ratios)
            variance = sum((x - mean) ** 2 for x in self._recent_ratios) / len(self._recent_ratios)
            jitter = min(.10, math.sqrt(max(0.0, variance)) * .06)
            predicted *= (1.0 + jitter)
        self.remaining_cost = max(0.0, predicted)
        self._last_predicted_seconds = self.remaining_cost
        return self.remaining_cost

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        old = self.mode
        self.mode = mode
        self.panic = (mode == PANIC)
        if mode == CATCH_UP and old == NORMAL:
            self.catch_up_activations += 1
        if mode == PANIC and old != PANIC:
            self.panic_activations += 1
        if old == CATCH_UP and mode == NORMAL:
            self._recovered_from_catchup += 1
        self._last_mode = old

    def _runtime_mode(self, left: float, predicted: float) -> str:
        if self.budget_seconds is None:
            return NORMAL
        if left <= RUNTIME_POLICY["hard_stop_guard_seconds"]:
            return PANIC
        ratio = predicted / max(.001, left)
        live = self._runtime_scale()
        # A measured slowdown should trigger catch-up slightly before the static
        # fit ratio does.  Panic still requires a plan that effectively no longer
        # fits, avoiding oscillation from one slow path.
        if ratio > RUNTIME_POLICY["panic_fit_ratio"]:
            return PANIC
        if self._global_samples >= 2 and live >= 1.35 and ratio >= .94:
            return PANIC
        if ratio >= RUNTIME_POLICY["catch_up_fit_ratio"]:
            return CATCH_UP
        if self._global_samples >= 2 and live >= 1.18 and ratio >= .76:
            return CATCH_UP
        return NORMAL

    def _strategy_for(self, mode: str) -> str:
        if mode == PANIC:
            return "structure-first / drop cleanup"
        if mode == CATCH_UP:
            return "coverage-first / trim low-value detail"
        return "planned-quality"

    def _consume(self, entry: dict[str, Any], *, skipped: bool = False):
        cost = self._cost(entry)
        op_type = self._op_type(entry)
        self._remaining_by_type[op_type] = max(0.0, self._remaining_by_type.get(op_type, 0.0) - cost)
        self._remaining_raw = max(0.0, self._remaining_raw - cost)
        if skipped:
            self.skipped += 1
            self.phase_skipped[self._phase(entry)] += 1
        self.predicted_remaining()

    def _skip(self, entry: dict[str, Any], reason: str, *, delta: float, coverage: float) -> SchedulerDecision:
        self._last_before = None
        self.skip_reasons[reason] += 1
        if "low-value" in reason:
            self.skipped_low_value += 1
        self._consume(entry, skipped=True)
        return SchedulerDecision(
            False, self.panic, reason, self.mode, delta, coverage,
            self.current_strategy, self.remaining_cost, self._runtime_scale(),
        )

    def before(self, entry: dict[str, Any]) -> SchedulerDecision:
        cost = self._cost(entry)
        op_type = self._op_type(entry)
        left = self.remaining_time()
        predicted = self.predicted_remaining()
        self.current_phase = self._phase(entry)
        self._last_before = self._now()
        self._last_entry_cost = cost
        self._last_entry_type = op_type

        if self.budget_seconds is None:
            self.current_strategy = "planned-quality"
            return SchedulerDecision(True, False, "unlimited", NORMAL, 0.0,
                                     self.structural_coverage(), self.current_strategy,
                                     predicted, self._runtime_scale())

        mode = self._runtime_mode(left, predicted)
        # Panic is sticky. Once the reserve is threatened, spending newly found
        # headroom on cleanup can recreate the same emergency seconds later.
        if self.mode == PANIC:
            mode = PANIC
        self._set_mode(mode)
        self.current_strategy = self._strategy_for(self.mode)
        delta = left - predicted
        coverage = self.structural_coverage()
        phase = self.current_phase
        importance = self._score(entry, "importance", .5)
        optional = bool(entry.get("optional"))

        if left <= RUNTIME_POLICY["hard_stop_guard_seconds"]:
            return self._skip(entry, "hard render budget reached", delta=delta, coverage=coverage)

        if cost*self._runtime_scale(op_type) > max(0.0,left-RUNTIME_POLICY["hard_stop_guard_seconds"]):
            return self._skip(entry, "dropped: operation does not fit remaining render budget", delta=delta, coverage=coverage)

        # Never spend early time on micro-detail while the drawing is still
        # missing its main silhouette.  This is independent from Panic mode and
        # therefore protects 60-80 second budgets from front-loaded detail.
        if phase in ("important_details", "accuracy", "correction") and coverage < RUNTIME_POLICY["structural_gate"]:
            return self._skip(entry, "structural coverage below 75%", delta=delta, coverage=coverage)

        if self.mode == PANIC:
            keep = phase in ("major_coverage", "structure")
            if phase == "important_details":
                # After the silhouette is largely complete, allow only truly
                # important details whose individual cost is small relative to
                # the remaining time (eyes/logo/key contour, not texture).
                max_detail_cost = max(.18, min(.80, left * .08))
                keep = (coverage >= RUNTIME_POLICY["panic_detail_min_structure"] and
                        importance >= RUNTIME_POLICY["panic_detail_min_importance"] and
                        cost * self._runtime_scale(op_type) <= max_detail_cost)
            if not keep:
                return self._skip(entry, "panic: low-value work dropped", delta=delta, coverage=coverage)

        elif self.mode == CATCH_UP:
            # Trim correction/cleanup first, then weak accuracy/detail. Structural
            # work remains untouched.  Optional paths have the lowest threshold.
            drop = (
                (phase == "correction" and importance < RUNTIME_POLICY["catchup_correction_min_importance"]) or
                (phase == "accuracy" and importance < RUNTIME_POLICY["catchup_accuracy_min_importance"]) or
                (phase == "important_details" and optional and importance < .56) or
                (optional and importance < .50)
            )
            if drop:
                return self._skip(entry, "catch-up: low-value work dropped", delta=delta, coverage=coverage)

        return SchedulerDecision(
            True, self.panic, "execute", self.mode, delta, coverage,
            self.current_strategy, predicted, self._runtime_scale(op_type),
        )

    def _learn_runtime_sample(self, estimated: float, actual: float, op_type: str):
        if not math.isfinite(estimated) or estimated <= .0005 or actual < 0 or not math.isfinite(actual):
            return
        ratio = actual / max(.0005, estimated)
        ratio = max(RUNTIME_POLICY["sample_ratio_min"], min(RUNTIME_POLICY["sample_ratio_max"], ratio))
        alpha = RUNTIME_POLICY["ema_alpha"]
        if self._global_samples <= 0:
            ratio=max(.5,min(2.5,ratio))
            self._global_ratio_ema = ratio
        else:
            self._global_ratio_ema = self._global_ratio_ema * (1.0 - alpha) + ratio * alpha
        self._global_samples += 1
        typed_samples = self._type_samples.get(op_type, 0)
        old = self._type_ratio_ema.get(op_type, ratio)
        self._type_ratio_ema[op_type] = ratio if typed_samples <= 0 else old * (1.0 - alpha) + ratio * alpha
        self._type_samples[op_type] = typed_samples + 1
        self._recent_ratios.append(ratio)

    def after(self, entry: dict[str, Any], *, excluded_seconds: float = 0.0):
        now = self._now()
        actual = 0.0
        if self._last_before is not None:
            actual = max(0.0, now - self._last_before - max(0.0,excluded_seconds))
            self._actual_active_seconds += actual
        had_start = self._last_before is not None
        self._last_before = None
        cost = self._cost(entry)
        op_type = self._op_type(entry)
        self._last_actual_seconds = actual
        self._estimated_executed_seconds += cost
        if had_start:
            self._learn_runtime_sample(cost, actual, op_type)
        self._consume(entry, skipped=False)
        self.executed += 1
        self.phase_executed[self._phase(entry)] += 1
        if self._is_structural(entry):
            self.structural_done += self._structural_weight(entry)

    @staticmethod
    def _transition_count(entries) -> int:
        """Count colour/brush transitions without assigning any UI timing."""
        transitions=0;last_color=object();last_brush=object();started=False
        for raw in entries or ():
            entry=dict(raw)
            if not DeadlineScheduler._is_drawing(entry):
                continue
            color=entry.get("color_index");brush=entry.get("brush_px")
            if started and (color!=last_color or brush!=last_brush):transitions+=1
            last_color=color;last_brush=brush;started=True
        return transitions

    def _replan_priority(self, entry, original_index: int):
        phase=self._phase(entry);importance=self._score(entry,"importance",.5)
        structural=self._score(entry,"structural_score",0.0);optional=bool(entry.get("optional"))
        adjusted=self._cost(entry)*self._runtime_scale(self._op_type(entry))
        if self.mode == PANIC:
            if phase in ("major_coverage","structure"):tier=0
            elif phase == "important_details" and importance >= RUNTIME_POLICY["panic_detail_min_importance"]:tier=1
            else:tier=2
            value=max(structural,importance)
        else:
            value=max(structural*.92,importance)
            tier=0 if (not optional and value>=.70) else (1 if not optional else 2)
        # Original index is the final tie-breaker, keeping the sort deterministic.
        return (tier,-round(value,6),round(adjusted,6),original_index)

    def replan_remaining(self, remaining, *, force: bool = False):
        """Reorder only already-safe remaining paths inside contiguous phase barriers.

        Geometry, colour, brush width and phase membership are immutable. Non-stroke
        operations are hard barriers. A candidate is rejected when it would increase
        colour/brush transitions, so catch-up cannot become slower by UI thrashing.
        """
        rows=[dict(entry) for entry in (remaining or ())]
        if len(rows)<2 or self.budget_seconds is None or self.mode == NORMAL:return rows
        scale=self._runtime_scale()
        if not force:
            if self._global_samples < 2:return rows
            sample_gap=self._global_samples-self._last_replan_sample
            scale_delta=abs(scale-self._last_replan_scale)
            if self.mode==self._last_replan_mode and sample_gap<2 and scale_delta<.12:return rows
        output=[];moved=0;rejected=0;start=0
        while start<len(rows):
            first=rows[start];op=self._op_type(first);phase=self._phase(first)
            if not self._is_drawing(first):
                output.append(first);start+=1;continue
            end=start+1
            while end<len(rows) and self._is_drawing(rows[end]) and self._phase(rows[end])==phase:
                end+=1
            block=rows[start:end]
            indexed=list(enumerate(block))
            ranked=sorted(indexed,key=lambda pair:self._replan_priority(pair[1],pair[0]))
            candidate=[entry for _idx,entry in ranked]
            if [idx for idx,_entry in ranked] != list(range(len(block))):
                previous = next((entry for entry in reversed(output) if self._is_drawing(entry)), None)
                following = next((rows[index] for index in range(end, len(rows))
                                  if self._is_drawing(rows[index])), None)
                prefix = [previous] if previous is not None else []
                suffix = [following] if following is not None else []
                if self._transition_count(prefix + candidate + suffix) <= self._transition_count(prefix + block + suffix):
                    moved += sum(1 for pos,(idx,_entry) in enumerate(ranked) if pos!=idx)
                    block=candidate
                else:
                    rejected+=1
            output.extend(block);start=end
        self._last_replan_sample=self._global_samples
        self._last_replan_mode=self.mode
        self._last_replan_scale=scale
        if moved:
            self.replan_count+=1;self.reordered_paths+=moved
        self.replan_rejected_switch_cost+=rejected
        return output

    def prediction_interval(self):
        """Heuristic variability envelope, not a statistical confidence interval."""
        center=self.predicted_remaining()
        if len(self._recent_ratios)<3:
            return {"lower_seconds":max(0.0,center*.5),"upper_seconds":center*2.0,
                    "source":"cold-start heuristic", "samples":len(self._recent_ratios)}
        values=sorted(self._recent_ratios)
        median=values[len(values)//2]
        deviations=sorted(abs(value-median) for value in values)
        spread=max(.10,min(1.0,2.0*deviations[len(deviations)//2]/max(.25,median)))
        return {"lower_seconds":max(0.0,center*(1.0-spread)),
                "upper_seconds":center*(1.0+spread),
                "source":"recent runtime variability heuristic", "samples":len(values)}

    def telemetry(self) -> dict[str, Any]:
        elapsed = self.elapsed()
        left = self.remaining_time()
        predicted = self.predicted_remaining()
        delta = None if self.budget_seconds is None else left - predicted
        ops_per_second = self.executed / max(.001, self._actual_active_seconds or elapsed) if self.executed else 0.0
        work_rate = self._estimated_executed_seconds / max(.001, self._actual_active_seconds) if self._actual_active_seconds else 0.0
        live_multiplier = self._runtime_scale()
        return {
            "elapsed_seconds": round(elapsed, 3),
            "remaining_budget_seconds": None if self.budget_seconds is None else round(left, 3),
            "predicted_remaining_seconds": round(predicted, 3),
            "predicted_finish_seconds": round(elapsed + predicted, 3),
            "schedule_delta_seconds": None if delta is None else round(delta, 3),
            "operations_per_second": round(ops_per_second, 3),
            "estimated_work_seconds_per_real_second": round(work_rate, 3),
            "runtime_cost_multiplier": round(live_multiplier, 4),
            "runtime_samples": int(self._global_samples),
            "prediction_interval": self.prediction_interval(),
            "progress_evidence": "sent operations; visual verification is separate",
            "last_operation_actual_seconds": round(self._last_actual_seconds, 4),
            "skipped_low_value": int(self.skipped_low_value),
            "current_phase": self.current_phase,
            "mode": self.mode,
            "strategy": self.current_strategy,
            "structural_coverage_percent": round(self.structural_coverage() * 100.0, 2),
            "phase_executed": dict(self.phase_executed),
            "phase_skipped": dict(self.phase_skipped),
            "skip_reasons": dict(self.skip_reasons),
            "recovered_from_catchup": int(self._recovered_from_catchup),
            "dynamic_replans": int(self.replan_count),
            "reordered_remaining_paths": int(self.reordered_paths),
            "replans_rejected_switch_cost": int(self.replan_rejected_switch_cost),
            "last_replan_mode": self._last_replan_mode,
        }

    def meta(self) -> dict[str, Any]:
        out = self.telemetry()
        out.update({
            "remaining_time_seconds": out.get("remaining_budget_seconds"),
            "remaining_predicted_seconds": out.get("predicted_remaining_seconds"),
            "executed_paths": self.executed,
            "skipped_paths": self.skipped,
            "panic_mode": bool(self.panic),
            "panic_activations": int(self.panic_activations),
            "catch_up_activations": int(self.catch_up_activations),
            "runtime_prediction_source": "live measured execution EMA + typed planning cost",
            "panic_policy": "coverage -> structure -> exceptionally important detail; accuracy/correction dropped",
            "hard_budget_guard_seconds": RUNTIME_POLICY["hard_stop_guard_seconds"],
        })
        return out
