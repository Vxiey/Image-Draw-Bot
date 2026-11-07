"""Bounded mixed-colour scoring keeps real palette plans and Bayer ownership."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import inspect
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdvancedColor as color
import Colors
import DrawBot
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch17_layered_diagnostics import (
    BAYER, calibrated, drawn_labels, plan_options, raster_statistics)


PALETTE = tuple(rgb for name, rgb in Colors.DEFAULT_COLORS)
NAMES = tuple(name for name, rgb in Colors.DEFAULT_COLORS)
SOURCE_RGB = ((128, 85, 60), (48, 151, 122), (182, 72, 152), (110, 120, 136),
              (234, 167, 80), (80, 94, 190), (162, 212, 140), (30, 50, 64))
LAYER_MODES = ('Light shading', 'Dual-color mix', 'Full color mix')


def block_source(size=(48, 32)):
    width, height = size
    image = Image.new('RGBA', size)
    image.putdata([(*SOURCE_RGB[min(3, x * 4 // width) + 4 * min(1, y * 2 // height)], 255)
                   for y in range(height) for x in range(width)])
    return image


def clear_layer_caches(module=color):
    module._best_layer_cached.cache_clear()
    module._closest_palette_index_cached.cache_clear()


def layer_plan_options(mode='Full color mix'):
    # The actual controller supplies a resolved resource allocation. Keep that
    # input fixed so live free-RAM observations cannot change parity metadata.
    options = plan_options()
    options.update(color_layers=mode, cpu_workers='1', cpu_workers_resolved=1,
                   cpu_engine='Threads', ram_budget='512 MB', ram_budget_mb=512,
                   logical_cpus=4, available_ram_mb=8192)
    return options


@contextmanager
def scoring_work(module=color):
    costs = Counter()
    mixes = Counter()
    original_cost, original_mix = module.palette_match_cost, module._mix
    def score(source, candidate, **kwargs):
        costs[(tuple(source), tuple(candidate), kwargs['color_rendering'], kwargs['fidelity'])] += 1
        return original_cost(source, candidate, **kwargs)
    def mix(first, second, ratio):
        result = original_mix(first, second, ratio)
        mixes[result] += 1
        return result
    with patch.object(module, 'palette_match_cost', score), patch.object(module, '_mix', mix):
        yield costs, mixes


def build(source, mode='Full color mix', **changes):
    settings = dict(lines=True, skip_white=False, color_rendering='Layered color mix',
                    color_layers=mode, color_fidelity='Balanced', gpu_mode='CPU')
    settings.update(changes)
    return color.build_color_strokes(source, **settings)


class MixedCostReuseTests(unittest.TestCase):
    def tearDown(self):
        clear_layer_caches()

    def test_actual_builder_and_public_planner_reduce_scoring_without_skipping_candidates(self):
        # Actual old calls: 1352 / 5192 / 10088. Mixture enumeration and the
        # palette/nearest scorer remain unchanged; only identical mix scores share.
        expected = {'Light shading': (1352, 1056, 832, 384),
                    'Dual-color mix': (3952, 4896, 1184, 576),
                    'Full color mix': (6392, 9792, 1168, 564)}
        with calibrated(PALETTE, names=NAMES), closing(block_source()) as source:
            pixels = source.tobytes()
            for public in (False, True):
                for mode in LAYER_MODES:
                    with self.subTest(public=public, mode=mode):
                        clear_layer_caches()
                        plan = None
                        try:
                            with scoring_work() as (costs, mixes):
                                if public:
                                    settings = layer_plan_options(mode)
                                    plan = DrawBot.make_plan(source, source.size, settings)
                                    count = plan['count']
                                    meta = plan['options']['advanced_color_meta']
                                else:
                                    groups, meta = build(source, mode)
                                    count = sum(map(len, groups))
                                    drawn_labels(source, groups, skip_white=False)
                            self.assertEqual((sum(costs.values()), sum(mixes.values()),
                                              count, meta['layered_pixels']), expected[mode])
                            self.assertEqual(source.tobytes(), pixels)
                        finally:
                            if plan is not None:
                                close_plan(plan, source)

    def test_exact_midpoint_and_duplicate_swatch_ties_keep_ordered_choices(self):
        palette = ((0, 0, 0), (255, 255, 255), (0, 0, 0), (255, 255, 255))
        names = ('Black', 'White', 'Custom black', 'Custom white')
        with calibrated(palette, names=names):
            for mode in ('Dual-color mix', 'Full color mix'):
                for workflow, first, second in (('Calibrated palette', 1, 0),
                                                 ('Custom colors first', 1, 0),
                                                 ('Custom colors only', 3, 2)):
                    with self.subTest(mode=mode, workflow=workflow):
                        # round(255 * .5) is exactly 128. Both ordered pairs
                        # produce this RGB; the first eligible tied pair wins.
                        actual = color.best_layer_for_rgb((128, 128, 128),
                            color_layers=mode, custom_mode=workflow)
                        self.assertEqual(actual, (first, second, .5, 1.0))
            self.assertEqual(color.best_layer_for_rgb((0, 0, 0),
                color_layers='Full color mix', custom_mode='Custom colors first'),
                (2, None, 0.0, 0.0))
            self.assertEqual(color.best_layer_for_rgb((90, 90, 90),
                color_layers='Full color mix', custom_mode='Custom colors only'),
                (3, 2, .65, .9917638798580002))
            with closing(Image.new('RGBA', (8, 8), (128, 128, 128, 255))) as source:
                for lines in (False, True):
                    groups, meta = build(source, lines=lines, custom_color_workflow='Custom colors only')
                    labels = drawn_labels(source, groups, skip_white=False)
                    expected = np.array([[2 if BAYER[y % 4][x % 4] < 8 else 3
                                          for x in range(8)] for y in range(8)])
                    np.testing.assert_array_equal(labels, expected)
                    self.assertEqual(meta['color_fidelity_diagnostics'],
                                     raster_statistics(source, labels, palette))

    def test_real_thread_and_process_builders_keep_identical_complete_output(self):
        with calibrated(PALETTE, names=NAMES), closing(block_source((256, 196))) as source:
            clear_layer_caches()
            expected_groups, expected_meta = build(source, cpu_workers=1)
            for engine, backend in (('Threads', 'threads'), ('Processes', 'processes')):
                with self.subTest(engine=engine):
                    clear_layer_caches()
                    groups, meta = build(source, cpu_workers=2, cpu_engine=engine)
                    self.assertEqual(meta['cpu_backend'], backend)
                    self.assertGreater(meta['cpu_chunks'], 1)
                    self.assertEqual(groups, expected_groups)
                    self.assertEqual({k: v for k, v in meta.items() if k not in ('cpu_backend', 'cpu_chunks')},
                                     {k: v for k, v in expected_meta.items() if k not in ('cpu_backend', 'cpu_chunks')})
                    drawn_labels(source, groups, skip_white=False)

    def test_completed_and_failing_queries_do_not_retain_their_mixed_score_tables(self):
        for failure in (None, InterruptedError('stop in scorer'), RuntimeError('scorer failed')):
            with self.subTest(failure=type(failure).__name__), calibrated(PALETTE, names=NAMES):
                clear_layer_caches()
                original = color.palette_match_cost
                tables = []
                def observed(source, candidate, **kwargs):
                    table = inspect.currentframe().f_back.f_locals.get('mixed_costs')
                    if table is not None and len(table) >= 2:
                        if not tables:
                            tables.append(table)
                            if failure is not None:
                                raise failure
                    return original(source, candidate, **kwargs)
                retained = None
                with patch.object(color, 'palette_match_cost', observed):
                    try:
                        color.best_layer_for_rgb(SOURCE_RGB[0], color_layers='Full color mix')
                    except (InterruptedError, RuntimeError) as error:
                        retained = error
                self.assertIs(retained, failure)
                self.assertEqual(len(tables), 1)
                self.assertEqual(tables[0], {})
                self.assertEqual(color._best_layer_cached.cache_info().currsize, 1 if failure is None else 0)
                if failure is not None:
                    self.assertIsNotNone(retained.__traceback__)

    def test_concurrent_public_queries_own_separate_tables_and_cache_only_the_winner(self):
        with calibrated(), ThreadPoolExecutor(max_workers=2) as executor:
            clear_layer_caches()
            barrier = threading.Barrier(2)
            original = color.palette_match_cost
            tables = {}
            def observed(source, candidate, **kwargs):
                table = inspect.currentframe().f_back.f_locals.get('mixed_costs')
                thread = threading.get_ident()
                if table is not None and thread not in tables:
                    tables[thread] = table
                    barrier.wait(timeout=10)
                return original(source, candidate, **kwargs)
            with patch.object(color, 'palette_match_cost', observed):
                futures = [executor.submit(color.best_layer_for_rgb, (gray, gray, gray),
                                           color_layers='Full color mix') for gray in (128, 90)]
                values = [future.result(timeout=15) for future in futures]
            self.assertEqual(values, [(1, 0, .5, 1.0), (1, 0, .65, .9917638798580002)])
            self.assertEqual(len(tables), 2)
            self.assertEqual(len({id(table) for table in tables.values()}), 2)
            self.assertTrue(all(table == {} for table in tables.values()))
            self.assertEqual(color._best_layer_cached.cache_info().currsize, 2)

    def test_existing_nonlayered_controls_do_no_mixture_work_and_palette_changes_stay_fresh(self):
        with calibrated():
            for rendering, layers in (('RGB nearest', 'Full color mix'), ('Perceptual match', 'Off')):
                clear_layer_caches()
                with scoring_work() as (_costs, mixes):
                    result = color.best_layer_for_rgb((128, 128, 128),
                        color_rendering=rendering, color_layers=layers)
                self.assertIsNone(result[1])
                self.assertFalse(mixes)
            first = color.best_layer_for_rgb((128, 128, 128), color_layers='Full color mix')
            self.assertEqual(first, (1, 0, .5, 1.0))
            with calibrated(((128, 128, 128),), names=('Exact gray',)):
                with scoring_work() as (_costs, mixes):
                    next_result = color.best_layer_for_rgb((128, 128, 128), color_layers='Full color mix')
                self.assertEqual(next_result, (0, None, 0.0, 0.0))
                self.assertFalse(mixes)
            self.assertEqual(color.best_layer_for_rgb((128, 128, 128), color_layers='Full color mix'), first)


if __name__ == '__main__':
    unittest.main()
