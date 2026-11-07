"""One bounded, read-only observation of a retained drawing's visible canvas.

The controller owns requests and borrowed plan/source images. This worker helper
owns only its temporary capture; it never invokes a drawing executor or arms,
activates, moves or clicks a native input backend.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import threading
import time

from PIL import Image

from SafeCanvasSnapshotScoring import score_final_canvas_snapshot, validated_comparison_size

RECHECK_SECONDS = 15.0


def _target(value):
    handle, rect = value
    return int(handle), tuple(rect)


@dataclass(eq=False)
class ResultRecheckRequest:
    plan: dict | None
    source: Image.Image | None
    profile_name: str
    profile_key: str
    target: tuple
    area: tuple
    client_rect: tuple
    dpi: int | None
    cancelled: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self):
        self.target = _target(self.target)
        self.area = tuple(self.area)
        self.client_rect = tuple(self.client_rect or ())

    def cancel(self):
        self.cancelled.set()

    def release(self):
        # These images belong to the controller/plan; never close them here.
        self.plan = None
        self.source = None

    def matches(self, *, plan, source, profile_name, profile_key, target, area,
                client_rect, dpi):
        if self.cancelled.is_set() or self.plan is None:
            return False
        try:
            return (self.plan is plan and self.source is source
                    and self.profile_name == profile_name and self.profile_key == profile_key
                    and self.target == _target(target) and self.area == tuple(area)
                    and self.client_rect == tuple(client_rect or ()) and self.dpi == dpi)
        except (TypeError, ValueError, OverflowError):
            return False


@dataclass(frozen=True)
class ResultRecheckResult:
    request: ResultRecheckRequest
    metrics: dict
    history: dict
    history_error: str = ''


def _unavailable(error):
    return {'available': False, 'trusted': False, 'feedback_trust': 'none',
            'scoring_state': 'unavailable', 'reason': str(error)[:240],
            'capture_pixels_persisted': False, 'image_pixels_persisted': False,
            'stores_image_data': False}


def recheck_result(request, mouse, stop, wait, report, *, current=lambda: True,
                   clock=time.monotonic, seconds=RECHECK_SECONDS):
    """Capture and score once, returning compact evidence for UI adoption.

    ``mouse`` is the actual GuardedMouse wrapper. ``current`` reads only plain
    controller identities, never Tk variables. The deadline is cooperative:
    native capture/resize calls already in progress cannot be preempted.
    """
    deadline = clock() + float(seconds)

    def check():
        if request.cancelled.is_set() or stop.is_set() or not current():
            raise InterruptedError('Result re-check cancelled.')
        if clock() >= deadline:
            raise TimeoutError('Result re-check exceeded its bounded analysis time.')

    def cancelled():
        check()
        return False

    def verify_geometry():
        check()
        monitor = mouse.monitor
        handle, rect = request.target
        if tuple(monitor.rectangle(handle)) != rect:
            raise ValueError('The target window moved or changed size. Re-select the canvas before re-checking.')
        if request.client_rect and tuple(monitor.client_rectangle(handle)) != request.client_rect:
            raise ValueError('The target client area changed. Re-select the canvas before re-checking.')
        if request.dpi is not None and monitor.dpi(handle) != request.dpi:
            raise ValueError('The target display scaling changed. Re-select the canvas before re-checking.')

    check()
    plan = request.plan
    options = dict(plan.get('options') or {})
    source = options.get('_accuracy_original_source')
    preview = plan.get('preview')
    layers = plan.get('ui_previews') or {}
    snapshot = None
    try:
        if not isinstance(source, Image.Image) or not isinstance(preview, Image.Image):
            raise ValueError('The retained drawing has no complete comparison images. Draw the image again before re-checking.')
        comparison_size = validated_comparison_size(preview.size)
        for second in (3, 2, 1):
            check()
            report(f'Re-checking the result in {second} s. Keep the target canvas visible. No input will be sent.')
            wait(1)
        verify_geometry()
        snapshot = mouse.snapshot_canvas(request.area)
        verify_geometry()
        acceptance = options.get('auto_tuner_acceptance_meta') or {}
        gates = acceptance.get('gates') or {}
        metrics = score_final_canvas_snapshot(
            snapshot=snapshot, original_source=source, area=request.area,
            fitted=plan['fitted'], comparison_size=comparison_size,
            simulated_final=preview, quantized_target=layers.get('quantized_target'),
            profile_key=request.profile_key,
            gpu_mode=options.get('gpu_mode', 'Auto'),
            visual_gate_percent=gates.get('visual_accuracy_min_percent'),
            # Observation time is not drawing time or new deadline evidence.
            actual_elapsed_seconds=None, usable_deadline_seconds=None,
            cancelled=cancelled)
        check()
    except InterruptedError as error:
        if request.cancelled.is_set() or stop.is_set() or not current():
            raise
        # Guarded capture also uses InterruptedError for occlusion/foreground
        # failures. They are unavailable fresh evidence, never an old PASS.
        metrics = _unavailable(error)
    except Exception as error:
        metrics = _unavailable(error)
    finally:
        if snapshot is not None:
            snapshot.close()
    if request.cancelled.is_set() or stop.is_set() or not current():
        raise InterruptedError('Result re-check cancelled.')
    metrics = deepcopy(metrics)
    metrics['observation'] = 'read-only result re-check'
    history = {}
    history_error = ''
    try:
        from CorrectionHistory import record_result_verification
        history = record_result_verification(
            dict(options, profile_key=request.profile_key, profile_name=request.profile_name),
            metrics, cancelled=lambda: request.cancelled.is_set() or stop.is_set() or not current())
    except InterruptedError:
        raise
    except Exception as error:
        history_error = str(error)[:240]
    if request.cancelled.is_set() or stop.is_set() or not current():
        raise InterruptedError('Result re-check cancelled.')
    return ResultRecheckResult(request, metrics, deepcopy(history), history_error)
