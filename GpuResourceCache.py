"""Maintain only CuPy resources this process has already used.

This registry does not discover devices, choose a compute policy, retain arrays,
or change backend health. The allocator remains the authority on which blocks
are unused; clearing its free blocks does not release any live allocation.
"""
from __future__ import annotations

from contextlib import contextmanager
import threading
import weakref


_LOCK = threading.RLock()
_CUDA_DEVICES = weakref.WeakKeyDictionary()
_MIB = 1024 * 1024


def remember_cuda_device(cp, device_id):
    """Record an already selected device without making tracking a failure path."""
    try:
        device_id = int(device_id)
        if device_id < 0:
            return
        with _LOCK:
            _CUDA_DEVICES.setdefault(cp, set()).add(device_id)
    except Exception:
        # Real CuPy modules are weak-referenceable. An optional provider or a
        # bookkeeping failure must not turn successful numeric work into error.
        return


def remember_current_cuda_device(cp):
    """Observe the current device only inside an existing CUDA operation."""
    try:
        remember_cuda_device(cp, cp.cuda.runtime.getDevice())
    except Exception:
        return


@contextmanager
def used_cuda_device(cp, device_id):
    with cp.cuda.Device(device_id) as device:
        remember_cuda_device(cp, device_id)
        yield device


def _cancel(cancelled):
    if cancelled():
        raise InterruptedError()


def clear_unused_cuda_cache(*, cancelled=lambda: False):
    """Trim known device/pinned pools without probing or synchronizing devices.

    CuPy's free_all_blocks releases free blocks, including their per-stream
    arenas. It can retain split blocks until all parts are free; measurements
    below therefore report the actual pool result, never promise zero VRAM.
    """
    _cancel(cancelled)
    with _LOCK:
        known = [(cp, sorted(devices)) for cp, devices in _CUDA_DEVICES.items()]
    devices = []
    errors = []
    pinned_pools = 0
    for cp, device_ids in known:
        for device_id in device_ids:
            _cancel(cancelled)
            try:
                # The context restores the caller thread's current device even
                # on failure. No other CUDA devices are opened or enumerated.
                with cp.cuda.Device(device_id):
                    pool = cp.get_default_memory_pool()
                    before_used = int(pool.used_bytes())
                    before_total = int(pool.total_bytes())
                    _cancel(cancelled)
                    pool.free_all_blocks()
                    after_used = int(pool.used_bytes())
                    after_total = int(pool.total_bytes())
                devices.append({
                    'device_id': device_id,
                    'before_used_bytes': before_used,
                    'before_total_bytes': before_total,
                    'after_used_bytes': after_used,
                    'after_total_bytes': after_total,
                })
            except InterruptedError:
                raise
            except Exception as error:
                errors.append(f'CUDA device {device_id}: {type(error).__name__}: {error}')
        _cancel(cancelled)
        try:
            # The default pinned pool is shared across this module's devices.
            # Its own free-block accounting protects live host transfers too.
            cp.get_default_pinned_memory_pool().free_all_blocks()
            pinned_pools += 1
        except InterruptedError:
            raise
        except Exception as error:
            errors.append(f'CUDA pinned pool: {type(error).__name__}: {error}')
    _cancel(cancelled)
    totals = {name: sum(item[name] for item in devices) for name in (
        'before_used_bytes', 'before_total_bytes', 'after_used_bytes', 'after_total_bytes')}
    return {
        'cuda_devices': devices, 'pinned_pools': pinned_pools, 'errors': errors,
        'before_free_bytes': max(0, totals['before_total_bytes'] - totals['before_used_bytes']),
        'after_free_bytes': max(0, totals['after_total_bytes'] - totals['after_used_bytes']),
        # Preserve the former public MB fields: cached meant the complete pool,
        # including its live allocations. The explicit free-byte fields do not.
        'before_used_mb': totals['before_used_bytes'] / _MIB,
        'before_cached_mb': totals['before_total_bytes'] / _MIB,
        'after_used_mb': totals['after_used_bytes'] / _MIB,
        'after_cached_mb': totals['after_total_bytes'] / _MIB,
    }
