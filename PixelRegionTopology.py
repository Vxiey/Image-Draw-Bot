"""One explicit, bounded topology handoff within a public Pixel operation.

The caller closes this owner before finalization/export and on earlier errors.
No component graph or label map enters a returned plan or persistent cache.
"""
from __future__ import annotations

import operator
import threading
import weakref

import numpy as np


MAX_LABEL_BYTES = 8 * 1024 * 1024
MAX_REGION_RECORDS = 65_536
VALIDATION_CHUNK_PIXELS = 65_536


class PixelRegionTopology:
    """Keep labels and seven integer fields; never keep full Components.

    Eligibility is intentionally conservative. Current public PixelMap output
    has contiguous integer indices and a contiguous bool drawable mask. Other
    representations, replaced arrays, subject/native maps and foreign threads
    retain the established fresh component-extraction path.

    Matching identity alone is insufficient: take() checks the effective
    target against labels and record colors in bounded chunks. In-place edits
    to visible colors or visibility therefore cause a fresh fallback too.
    """

    def __init__(self, pixel_map, *, max_label_bytes=MAX_LABEL_BYTES,
                 max_records=MAX_REGION_RECORDS):
        self._limit_bytes = operator.index(max_label_bytes)
        self._limit_records = operator.index(max_records)
        if self._limit_bytes < 0 or self._limit_records < 0:
            raise ValueError('Topology limits must be nonnegative.')
        self._thread = threading.current_thread()
        self._closed = False
        self._offered = False
        self._labels = self._records = None
        self._source_ref = self._index_ref = self._mask_ref = None
        self._shape = self._index_dtype = None
        try:
            self._shape = (operator.index(pixel_map.height), operator.index(pixel_map.width))
        except (TypeError, ValueError, OverflowError):
            self.close()
            return
        indices, mask = pixel_map.palette_index, pixel_map.drawable_mask
        if (not isinstance(indices, np.ndarray) or not isinstance(mask, np.ndarray)
                or indices.ndim != 2 or indices.shape != self._shape
                or mask.shape != self._shape or not np.issubdtype(indices.dtype, np.integer)
                or mask.dtype != np.dtype(bool)
                or not indices.flags.c_contiguous or not mask.flags.c_contiguous):
            self.close()
            return
        try:
            self._source_ref = weakref.ref(pixel_map)
            self._index_ref = weakref.ref(indices)
            self._mask_ref = weakref.ref(mask)
        except TypeError:
            self.close()
            return
        self._index_dtype = indices.dtype

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        self._labels = self._records = None
        self._source_ref = self._index_ref = self._mask_ref = None
        self._closed = True

    def _same_source_objects(self, pixel_map):
        try:
            shape = (operator.index(pixel_map.height), operator.index(pixel_map.width))
        except (TypeError, ValueError, OverflowError):
            return False
        return (not self._closed and self._thread is threading.current_thread()
                and self._source_ref is not None and self._source_ref() is pixel_map
                and self._index_ref() is pixel_map.palette_index
                and self._mask_ref() is pixel_map.drawable_mask
                and self._shape == shape
                and pixel_map.palette_index.shape == self._shape
                and pixel_map.drawable_mask.shape == self._shape
                and pixel_map.palette_index.dtype == self._index_dtype
                and pixel_map.drawable_mask.dtype == np.dtype(bool)
                and pixel_map.palette_index.flags.c_contiguous
                and pixel_map.drawable_mask.flags.c_contiguous)

    def offer(self, pixel_map, components, labels, *, cancelled=lambda: False):
        """Accept one private completed label map, or leave a fresh fallback.

        A record-allocation failure is optional-cache failure. Stop and other
        malformed-data exceptions still propagate. The component builder must
        clear its own label alias if this late offer raises; this method clears
        all its arguments/partial records for retained traceback safety.
        """
        if self._thread is not threading.current_thread():
            return False
        records = component = None
        accepted = False
        try:
            if cancelled():
                raise InterruptedError()
            if self._offered or not self._same_source_objects(pixel_map):
                return False
            self._offered = True
            if (not isinstance(labels, np.ndarray) or labels.dtype != np.dtype(np.int32)
                    or labels.shape != self._shape or not labels.flags.c_contiguous
                    or not labels.flags.owndata or labels.nbytes > self._limit_bytes
                    or len(components) > self._limit_records):
                return False
            records = np.empty((len(components), 7), dtype=np.int64)
            for serial, component in enumerate(components):
                if serial % 128 == 0 and cancelled():
                    raise InterruptedError()
                if int(component.component_id) != serial:
                    raise ValueError('Topology component IDs must retain their original order.')
                records[serial] = (int(component.component_id), int(component.color_index),
                                   int(component.area), *map(int, component.bbox))
            if cancelled():
                raise InterruptedError()
            records.flags.writeable = False
            self._labels, self._records = labels, records
            accepted = True
            return True
        except MemoryError:
            if cancelled():
                raise InterruptedError()
            return False
        finally:
            if not accepted:
                self.close()
            pixel_map = components = labels = records = component = None

    def _same_effective_target(self, pixel_map, *, cancelled):
        """Validate color+visibility from existing labels, without a source copy."""
        labels = records = indices = drawable = label_row = wanted = visible = None
        active = ids = colors = None
        try:
            if not self._same_source_objects(pixel_map) or self._labels is None:
                return False
            labels = self._labels.reshape(-1)
            records = self._records
            indices = pixel_map.palette_index.reshape(-1)
            drawable = pixel_map.drawable_mask.reshape(-1)
            for start in range(0, labels.size, VALIDATION_CHUNK_PIXELS):
                if cancelled():
                    raise InterruptedError()
                label_row = labels[start:start + VALIDATION_CHUNK_PIXELS]
                wanted = indices[start:start + VALIDATION_CHUNK_PIXELS]
                visible = drawable[start:start + VALIDATION_CHUNK_PIXELS]
                active = label_row >= 0
                if np.any(active != visible):
                    return False
                ids = label_row[active]
                if ids.size:
                    if np.any(ids >= len(records)):
                        return False
                    colors = records[ids, 1]
                    if np.any(wanted[active] != colors):
                        return False
            return True
        finally:
            pixel_map = labels = records = indices = drawable = label_row = wanted = visible = None
            active = ids = colors = None

    def take(self, pixel_map, *, cancelled=lambda: False):
        """Consume once; caller must clear returned label views on all exits."""
        if self._thread is not threading.current_thread() or self._closed:
            return None
        try:
            if cancelled():
                raise InterruptedError()
            if not self._same_effective_target(pixel_map, cancelled=cancelled):
                return None
            return self._records, self._labels
        except MemoryError:
            # Validation scratch is optional too. Keep the original fresh
            # scorer available if this bounded additional allocation fails.
            if cancelled():
                raise InterruptedError()
            return None
        finally:
            self.close()
            pixel_map = None
