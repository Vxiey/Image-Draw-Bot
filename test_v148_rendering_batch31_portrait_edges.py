"""Contour prefixes preserve real ranking while respecting the caller's budget."""
from contextlib import closing
from copy import deepcopy
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import DrawBot
import PortraitPlanner as portrait
from test_v148_rendering_batch29_portrait_preparation import (
    close_images, fingerprint, image_state, planner_fixture, source_image)


def plan_options(options, limit=None, dots=False):
    result = deepcopy(options)
    result.update(gpu_mode='CPU', detail=10, lines=not dots, delay=.025,
        unlimited_time=limit is None,
        time_budget_mode='Unlimited / Accuracy' if limit is None else 'Manual',
        manual_max_seconds=180 if limit is None else limit,
        max_seconds=180 if limit is None else limit)
    return result


class PortraitContourBudgetTests(unittest.TestCase):
    def test_actual_public_finite_plan_returns_only_its_used_contour_prefix(self):
        with planner_fixture(quality='High likeness') as (_, options), \
                closing(source_image(size=(73, 55), opaque=True)) as source:
            original = image_state(source)
            calls = []
            code = portrait._edge_strokes.__code__
            def observe(frame, event, value):
                if event == 'return' and frame.f_code is code and isinstance(value, list):
                    calls.append((len(frame.f_locals['occupied']),
                                  frame.f_back.f_locals['edge_budget'], len(value)))
            plan = None
            previous = sys.getprofile()
            try:
                try:
                    sys.setprofile(observe)
                    plan = DrawBot.make_plan(source, (128, 96), plan_options(options, 3))
                finally:
                    sys.setprofile(previous)
                self.assertEqual(len(calls), 1)
                winners, wanted, returned = calls[0]
                self.assertGreater(winners, wanted * 32)
                self.assertGreater(wanted, 0)
                self.assertEqual(returned, wanted,
                                 'The contour helper built a suffix discarded by its real caller')
                self.assertGreater(plan['count'], 0)
                self.assertEqual(image_state(source), original)
            finally:
                close_images(plan, (source,))

    def test_bounded_contours_match_the_full_stable_ranking_including_ties(self):
        y, x = np.indices((47, 63))
        fixtures = (((x // 3) % 2) * 220 + 15, (x * 19 + y * 31) % 256)
        for fixture in fixtures:
            with closing(Image.fromarray(fixture.astype(np.uint8))) as gray:
                gray.info['marker'] = 'borrowed contour source'
                original = image_state(gray)
                for quality in ('Balanced', 'High likeness', 'Maximum likeness'):
                    for focus in (False, True):
                        metadata = {}
                        full = portrait._edge_strokes(gray, 10, lambda: False,
                            draw_quality=quality, subject_focus=focus, gpu_mode='CPU',
                            acceleration_meta=metadata)
                        self.assertTrue(full)
                        for wanted in (0, 1, 6, 31, len(full) // 2, len(full), len(full) + 7):
                            with self.subTest(quality=quality, focus=focus, wanted=wanted):
                                current_metadata = {}
                                actual = portrait._edge_strokes(gray, 10, lambda: False,
                                    draw_quality=quality, subject_focus=focus, gpu_mode='CPU',
                                    acceleration_meta=current_metadata, max_strokes=wanted)
                                self.assertEqual(actual, full[:wanted])
                                self.assertEqual(current_metadata, metadata)
                                self.assertEqual(image_state(gray), original)

    def test_complete_public_plans_match_the_original_full_result_then_slice_boundary(self):
        actual_edge = portrait._edge_strokes
        def full_then_slice(*args, max_strokes=None, **kwargs):
            result = actual_edge(*args, **kwargs)
            return result if max_strokes is None else result[:max_strokes]
        for quality, limit, dots, flat in (
            ('High likeness', 3, False, False),
            ('High likeness', 30, False, False),
            ('Balanced', None, False, False),
            ('High likeness', 3, False, True),
            ('Balanced', 3, True, False),
        ):
            with self.subTest(quality=quality, limit=limit, dots=dots, flat=flat), \
                    planner_fixture(quality=quality) as (_, options), \
                    closing(source_image(size=(73, 55), opaque=flat)) as source:
                if flat:
                    source.paste((255, 255, 255, 255), (0, 0, *source.size))
                original = image_state(source)
                before = after = None
                try:
                    with patch.object(portrait, '_edge_strokes', new=full_then_slice):
                        before = DrawBot.make_plan(source, (128, 96), plan_options(options, limit, dots))
                    after = DrawBot.make_plan(source, (128, 96), plan_options(options, limit, dots))
                    self.assertEqual(fingerprint(before), fingerprint(after))
                    self.assertEqual(image_state(source), original)
                finally:
                    close_images(before, (source,))
                    close_images(after, (source,))


if __name__ == '__main__':
    unittest.main()
