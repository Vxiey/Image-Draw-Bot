"""Property-based lossless raster tests for Image Draw Bot planners.

These tests intentionally use the independent RasterIdentity oracle rather than
Pillow so planner correctness is checked against exact integer pixels.
Install ``requirements-dev.txt`` to execute the 2,000 generated examples. The
module skips cleanly in runtime/release environments that intentionally install
only application dependencies.
"""
from __future__ import annotations

import unittest

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
except ImportError as error:  # pragma: no cover - exercised by runtime-only envs
    raise unittest.SkipTest("Install requirements-dev.txt to run raster property tests") from error

from ContinuousPaths import build_execution_paths
from ExtraFast2 import build_fast_paths
from RasterIdentity import compare_runs_to_paths


@st.composite
def axis_segment(draw):
    x = draw(st.integers(-32, 64))
    y = draw(st.integers(-32, 64))
    length = draw(st.integers(0, 28))
    direction = draw(st.sampled_from((-1, 1)))
    horizontal = draw(st.booleans())
    if horizontal:
        return (x, y, x + direction * length, y)
    return (x, y, x, y + direction * length)


axis_run_lists = st.lists(axis_segment(), min_size=0, max_size=28)

deadline_options = st.sampled_from(
    (
        {},
        {"time_budget_active": True, "max_seconds": 60},
        {"time_budget_active": True, "max_seconds": 120},
        {"time_budget_active": True, "max_seconds": 240},
        {"time_budget_active": True, "max_seconds": 600},
        {"time_budget_active": True, "max_seconds": 30, "unlimited_time": True},
        {"time_budget_active": True, "max_seconds": 30, "time_budget_mode": "Unlimited / Accuracy"},
    )
)


@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow,),
)
@given(axis_run_lists)
def test_continuous_paths_preserve_exact_axis_raster(runs):
    execution = build_execution_paths(
        [runs],
        enabled=True,
        max_rows_per_path=72,
        max_points_per_path=320,
    )
    report = compare_runs_to_paths(runs, execution[0])
    assert report.safe, report.as_dict()


@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow,),
)
@given(axis_run_lists, deadline_options)
def test_extra_fast_preserves_exact_axis_raster_for_all_deadline_policies(runs, options):
    execution, _meta = build_fast_paths([runs], dict(options))
    report = compare_runs_to_paths(runs, execution[0])
    assert report.safe, report.as_dict()
    assert len(execution[0]) <= len(runs)


class RasterIdentityPropertyTests(unittest.TestCase):
    """Expose the existing generated cases to CI's unittest discovery."""

    def test_continuous_paths_preserve_exact_axis_raster(self):
        test_continuous_paths_preserve_exact_axis_raster()

    def test_extra_fast_preserves_exact_axis_raster_for_all_deadline_policies(self):
        test_extra_fast_preserves_exact_axis_raster_for_all_deadline_policies()
