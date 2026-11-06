"""Stable front-end for the Microsoft Paint picture custom-palette workflow.

The production palette planner/cache/calibration implementation is preserved in
``PictureCustomPaletteLegacy``.  This module adds the bounded transaction layer
used for fragile RGB entry while keeping the existing public API intact.
"""
from __future__ import annotations

import time
from typing import Iterable, Sequence

import PictureCustomPaletteLegacy as _legacy
from UiTransactionRuntime import AdaptivePacer, UiTransaction

SCHEMA = _legacy.SCHEMA
PROFILE_KEY = _legacy.PROFILE_KEY
DEFAULT_MAX_COLORS = _legacy.DEFAULT_MAX_COLORS
MAX_ANALYSIS_DIMENSION = _legacy.MAX_ANALYSIS_DIMENSION
MAX_EDGE_SAMPLES = _legacy.MAX_EDGE_SAMPLES
PicturePalette = _legacy.PicturePalette

data_dir = _legacy.data_dir
atomic_write_text = _legacy.atomic_write_text

_rgb = _legacy._rgb
_visible_rgb = _legacy._visible_rgb
_analysis_image = _legacy._analysis_image
_validate_payload = _legacy._validate_payload
_distance2 = _legacy._distance2
_dedupe = _legacy._dedupe
_edge_detail_colors = _legacy._edge_detail_colors
_resolve_max_colors = _legacy._resolve_max_colors
_resolve_target = _legacy._resolve_target


def _sync_legacy_environment() -> None:
    _legacy.data_dir = data_dir
    _legacy.atomic_write_text = atomic_write_text


def image_fingerprint(image, *, cancelled=lambda: False) -> str:
    return _legacy.image_fingerprint(image, cancelled=cancelled)


def cache_path(image_fp: str, calibration_fp: str = ""):
    _sync_legacy_environment()
    return _legacy.cache_path(image_fp, calibration_fp)


def load_cached_palette(image_fp: str, calibration_fp: str, *, max_colors: int, fidelity: str):
    _sync_legacy_environment()
    return _legacy.load_cached_palette(
        image_fp, calibration_fp, max_colors=max_colors, fidelity=fidelity
    )


def save_palette(palette: PicturePalette):
    _sync_legacy_environment()
    return _legacy.save_palette(palette)


def build_picture_palette(image, palette_rgb, *, max_colors: int = DEFAULT_MAX_COLORS,
                          fidelity: str = "Faithful", calibration_fingerprint: str = "",
                          cancelled=lambda: False) -> PicturePalette:
    _sync_legacy_environment()
    return _legacy.build_picture_palette(
        image, palette_rgb, max_colors=max_colors, fidelity=fidelity,
        calibration_fingerprint=calibration_fingerprint, cancelled=cancelled,
    )


def apply_custom_rgb_sequence(mouse, keyboard_backend, controls: dict,
                              colors: Iterable[Sequence[int]], *, cancelled=lambda: False,
                              wait=time.sleep, progress=None, dialog_ready=None,
                              dialog_closed=None, color_ready=None, retry_limit: int = 1,
                              state_callback=None, input_guard=None) -> int:
    """Enter a picture palette into Paint with bounded verified retries.

    A colour is never committed with Paint's ``+`` button until the live RGB
    fields have been verified.  ``retry_limit`` defaults to one for historical
    API compatibility; the real Image Draw Bot Paint workflow enables three
    attempts through ``_production_apply_custom_rgb_sequence`` below.
    """
    required = ("OpenCustomColor", "RedField", "GreenField", "BlueField", "ConfirmColor")
    missing = [name for name in required if name not in controls]
    if missing:
        raise ValueError("Numeric Paint RGB controls are not calibrated: " + ", ".join(missing))

    controls = dict(controls)
    values = tuple(_rgb(c) for c in colors)
    dialog_open = False
    completed = 0
    transaction = UiTransaction(
        max_attempts=retry_limit,
        pacer=AdaptivePacer(base_delay=0.025, max_delay=0.30, growth=1.8, decay=0.72),
        cancelled=cancelled,
        wait=wait,
        on_state=state_callback,
    )

    def check_cancelled() -> None:
        transaction.check_cancelled("Picture custom palette cancelled.")

    from CalibrationValidation import screen_point

    def guard(point, *, modal=False):
        check_cancelled()
        if input_guard is not None:
            input_guard(point, modal=modal)
        else:
            verifier=getattr(mouse,'check_keyboard',None)
            if callable(verifier):verifier(modal_point=point if modal else None)
        check_cancelled()

    def click(name: str, delay: float = 0.04):
        point = screen_point(controls[name],label='Paint color control')
        modal=name!='OpenCustomColor'
        guard(point,modal=modal)
        mouse.move(*point)
        check_cancelled()
        wait(0.015)
        check_cancelled()
        actual=getattr(mouse,'get_position',lambda:point)()
        guard(screen_point(actual,label='Paint pointer'),modal=modal)
        mouse.click()
        check_cancelled()
        wait(delay)
        check_cancelled()
        return point

    def keyboard_command(point, operation, *args, **kwargs):
        guard(point,modal=True)
        operation(*args,**kwargs)
        check_cancelled()

    def refresh_dialog_controls() -> None:
        if dialog_ready is None:
            return
        check_cancelled()
        fresh = dialog_ready()
        check_cancelled()
        if fresh:
            controls.update(fresh)
        if "AddCustomColor" not in controls:
            raise ValueError("Paint + / Add to custom colors is not calibrated; no RGB input was sent.")

    if not values:
        return 0

    try:
        check_cancelled()
        guard(screen_point(controls['OpenCustomColor'],label='Paint Edit colors opener'))
        mouse.arm_input()
        check_cancelled()
        transaction.transition("OPEN_DIALOG", detail="open Paint Edit colors")
        click("OpenCustomColor", 0.16)
        dialog_open = True

        # Hard precondition: no numeric input before the live modal is proven ready.
        refresh_dialog_controls()
        if "AddCustomColor" not in controls:
            raise ValueError("Paint + / Add to custom colors is not calibrated; no RGB input was sent.")

        for index, rgb in enumerate(values, 1):
            check_cancelled()

            def write_and_verify(attempt: int):
                check_cancelled()
                if attempt > 1:
                    # XAML may recreate/move fields while Paint is catching up.
                    refresh_dialog_controls()
                transaction.transition(
                    "WRITE_VALUE", attempt=attempt, item_index=index, detail=f"RGB {rgb}"
                )
                settle = max(0.025, float(transaction.pacer.current_delay))
                for name, value in zip(("RedField", "GreenField", "BlueField"), rgb):
                    check_cancelled()
                    point=click(name, settle)
                    keyboard_command(point,keyboard_backend.press_and_release,"ctrl+a")
                    keyboard_command(point,keyboard_backend.write,str(int(value)),delay=0.01)
                    wait(settle)
                    check_cancelled()

                transaction.transition(
                    "VERIFY_VALUE", attempt=attempt, item_index=index, detail=f"RGB {rgb}"
                )
                if color_ready is not None:
                    check_cancelled()
                    fresh = color_ready(rgb)
                    check_cancelled()
                    if fresh:
                        controls.update(fresh)
                return True

            transaction.retry(
                write_and_verify,
                item_index=index,
                retry_on=(TimeoutError, ValueError),
                cancel_message="Picture custom palette cancelled.",
            )

            check_cancelled()
            transaction.transition(
                "COMMIT_VALUE", attempt=1, item_index=index,
                detail=f"Add RGB {rgb} to Paint custom colors",
            )
            # Commit once only. Blindly retrying this click could add duplicates.
            click("AddCustomColor", 0.25)
            wait(0.50)
            check_cancelled()

            transaction.transition(
                "VERIFY_COMMIT", attempt=1, item_index=index, detail=f"RGB {rgb}"
            )
            if dialog_ready is not None:
                check_cancelled()
                fresh = dialog_ready()
                check_cancelled()
                if fresh:
                    controls.update(fresh)

            completed += 1
            if progress is not None:
                progress(index, len(values), rgb)

        check_cancelled()
        click("ConfirmColor", 0.12)
        if dialog_closed is not None:
            dialog_closed()
            check_cancelled()
        dialog_open = False
        transaction.transition("DONE", item_index=completed, detail=f"{completed} colors prepared")
        check_cancelled()
    except Exception:
        if transaction.state not in ("FAILED", "DONE"):
            try:
                transaction.transition("FAILED", item_index=completed)
            except Exception:
                pass
        raise
    finally:
        try:
            if dialog_open and not cancelled():
                # A failed transaction may leave a modal open. Cleanup is only
                # allowed while its current ownership can still be established;
                # Stop never authorizes another keyboard command.
                if input_guard is not None or callable(getattr(mouse,'check_keyboard',None)):
                    point=screen_point(controls['ConfirmColor'],label='Paint color dialog')
                    keyboard_command(point,keyboard_backend.press_and_release,"esc")
                    wait(0.04)
        except Exception:
            pass
        finally:
            mouse.disarm_input()

    return completed


def _production_apply_custom_rgb_sequence(*args, **kwargs):
    """Production policy: tolerate two transient Paint misses, then fail safely."""
    kwargs.setdefault("retry_limit", 3)
    return apply_custom_rgb_sequence(*args, **kwargs)


# The preserved workflow still owns calibration, palette planning, persistence,
# focus guards and worker lifecycle. Only its fragile RGB transaction is swapped.
_legacy.apply_custom_rgb_sequence = _production_apply_custom_rgb_sequence


def start_picture_custom_palette(app) -> bool:
    _sync_legacy_environment()
    _legacy.apply_custom_rgb_sequence = _production_apply_custom_rgb_sequence
    return bool(_legacy.start_picture_custom_palette(app))


__all__ = [
    "SCHEMA", "PROFILE_KEY", "DEFAULT_MAX_COLORS", "MAX_ANALYSIS_DIMENSION",
    "MAX_EDGE_SAMPLES", "PicturePalette", "image_fingerprint", "cache_path",
    "load_cached_palette", "save_palette", "build_picture_palette",
    "apply_custom_rgb_sequence", "start_picture_custom_palette",
]
