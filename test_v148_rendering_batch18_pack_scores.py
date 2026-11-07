"""Reuse identical first-brush evidence without changing complete pack selection."""
from collections import Counter
from contextlib import ExitStack, closing
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveRegionHybrid as regional
import DrawBot
from ExecutionCostModel import build_cost_model
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_candidates import component
from test_v148_rendering_batch10_physical import physical_options, replay_executor
from test_v148_rendering_batch11_pack_choice import BLUE, FIXTURES


class CountedLabels(np.ndarray):
    def __array_finalize__(self, previous):
        self.full_scans = getattr(previous, 'full_scans', [])

    def __ge__(self, value):
        if np.isscalar(value) and value == 0:
            self.full_scans.append(self.shape)
        return np.asarray(self) >= value


class InitialBrushScoreTests(unittest.TestCase):
    def test_one_initial_geometry_search_serves_all_ladders_and_both_policies(self):
        labels = np.ones((64, 96), np.int32)
        labels.flags.writeable = False
        options = physical_options((100, 100), (96, 64))
        model = build_cost_model(options, (96, 64), (96, 64))
        original = regional._eroded_centers
        calls = Counter()
        def observed(target, brush, **kwargs):
            calls[brush] += 1
            return original(target, brush, **kwargs)
        with patch.object(regional, '_eroded_centers', side_effect=observed):
            result, reason = regional._brush_pack_candidate(component(labels.shape), labels, options, model)
        self.assertIsNotNone(result, reason)
        self.assertEqual(result['covered_pixels'], labels.size)
        self.assertGreater(result['ladder_candidates_evaluated'], 1)
        self.assertEqual(set(result['packing_policy_candidates']), {'gain-per-cost', 'maximum-gain'})
        self.assertEqual(calls[16], 1, 'The first target/residual is identical across every ladder/policy')
        np.testing.assert_array_equal(labels, np.ones((64, 96), np.int32))

    def test_existing_component_drawable_total_is_not_recomputed_from_the_whole_canvas(self):
        labels = np.ones((64, 96), np.int32).view(CountedLabels)
        labels.full_scans = []
        labels.flags.writeable = False
        options = physical_options((100, 100), (96, 64))
        model = build_cost_model(options, (96, 64), (96, 64))
        comp = component(labels.shape)
        comp.horizontal_runs = [(0, y, 95, y) for y in range(64)]
        comp.vertical_runs = [(x, 0, x, 63) for x in range(96)]
        choice, sequence, _meta = regional._choose_component(comp, labels,
            labels.size, model, options)
        self.assertTrue(sequence)
        self.assertEqual(choice.method, 'region-brush-pack')
        self.assertEqual(labels.full_scans, [])

    def test_actual_public_pack_policies_keep_native_rasters_with_one_initial_search(self):
        for name, (size, area, box) in FIXTURES.items():
            with self.subTest(fixture=name), ExitStack() as stack:
                stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                source = stack.enter_context(closing(Image.new('RGB', size, 'white')))
                ImageDraw.Draw(source).rectangle(box, fill=BLUE)
                calls = []
                erosion = regional._eroded_centers
                def observed(target, brush, **kwargs):
                    if brush == 16:
                        calls.append((target.shape, id(target)))
                    return erosion(target, brush, **kwargs)
                with patch.object(regional, '_eroded_centers', side_effect=observed):
                    plan = DrawBot.make_plan(source, area, physical_options((100, 100), area))
                stack.callback(close_plan, plan, source)
                actual, selected = replay_executor(plan, (100, 100), area)
                expected = np.full((area[1], area[0]), -1, np.int32)
                sx, sy = area[0] // size[0], area[1] // size[1]
                expected[box[1]*sy:(box[3]+1)*sy, box[0]*sx:(box[2]+1)*sx] = plan['colors'].index(BLUE)
                np.testing.assert_array_equal(actual, expected)
                self.assertTrue(set(selected) <= {2, 4, 8, 16})
                self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
                self.assertEqual(len(calls), 1)

    def test_cache_is_one_component_local_and_cleared_on_success_and_stop(self):
        labels = np.ones((32, 48), np.int32)
        options = physical_options((100, 100), (48, 32))
        model = build_cost_model(options, (48, 32), (48, 32))
        helper = regional._candidate_paths_for_brush
        for interrupt in (False, True):
            with self.subTest(stop=interrupt):
                caches, masks, stopped, kept = [], [], [], []
                def inspect(*args, **kwargs):
                    cache = kwargs.get('_layout_cache')
                    if cache is not None:
                        caches.append(cache)
                        if interrupt and len(caches) == 2:
                            stopped.append(True)
                    result = helper(*args, **kwargs)
                    if cache:
                        self.assertEqual(len(cache), 1)
                        mask, rows = next(iter(cache.values()))
                        masks.append(weakref.ref(mask))
                        self.assertTrue(all(all(isinstance(value, (int, float, str)) for value in row)
                                            for row in rows))
                    return result
                with patch.object(regional, '_candidate_paths_for_brush', side_effect=inspect):
                    try:
                        result, reason = regional._brush_pack_candidate(component(labels.shape), labels,
                            options, model, cancelled=lambda: bool(stopped))
                    except InterruptedError as error:
                        kept.append(error)
                    else:
                        self.assertFalse(interrupt)
                        self.assertIsNotNone(result, reason)
                self.assertGreaterEqual(len(caches), 2)
                self.assertEqual(len({id(cache) for cache in caches}), 1)
                self.assertTrue(all(not cache for cache in caches))
                self.assertTrue(masks)
                self.assertTrue(all(ref() is None for ref in masks))
                if interrupt:
                    self.assertTrue(kept[0].__traceback__)

    def test_empty_first_brush_search_is_reused_without_changing_residual_repair(self):
        labels = np.full((32, 48), -1, np.int32)
        labels[:4, :] = labels[-4:, :] = 1
        labels[:, :4] = labels[:, -4:] = 1
        options = physical_options((100, 100), (48, 32))
        model = build_cost_model(options, (48, 32), (48, 32))
        comp = component(labels.shape)
        comp.area = int(np.count_nonzero(labels == 1))
        erosion, calls = regional._eroded_centers, Counter()
        def observed(target, brush, **kwargs):
            calls[brush] += 1
            return erosion(target, brush, **kwargs)
        with patch.object(regional, '_eroded_centers', side_effect=observed):
            packed, reason = regional._brush_pack_candidate(comp, labels, options, model)
        self.assertIsNotNone(packed, reason)
        self.assertEqual(calls[16], 1)
        self.assertEqual(packed['covered_pixels'], comp.area)
        self.assertEqual(set(packed['used_brush_sizes']) - {2, 4}, set())


if __name__ == '__main__':
    unittest.main()
