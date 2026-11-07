"""Real palette/planner calls prepare each unchanged region state only once."""
from collections import Counter
from contextlib import closing, contextmanager
import copy
from dataclasses import replace
import gc
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import DrawBot
import DynamicColors as dynamic
import RegionAwareQuantization as regions
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch17_layered_diagnostics import calibrated, plan_options


PALETTE = ((0, 0, 0), (255, 255, 255), (230, 30, 20), (25, 190, 60),
           (30, 70, 220), (235, 200, 30), (200, 40, 180), (25, 190, 195))


def region_graphic(size=(96, 72)):
    width, height = size
    colors = np.random.default_rng(1481901).integers(20, 230, (32, 3), dtype=np.uint8)
    x = np.arange(width)[None, :]
    y = np.arange(height)[:, None]
    labels = ((x // 8) * 3 + (y // 6) * 7) % len(colors)
    pixels = np.empty((height, width, 4), np.uint8)
    pixels[..., :3] = colors[labels]
    pixels[..., 3] = 255
    pixels[::17, ::5, 3] = 0
    pixels[1::17, ::7, 3] = 128
    pixels[-3:, -9:] = (255, 255, 255, 255)
    return Image.fromarray(pixels)


@contextmanager
def preparation_counts():
    """Count real weighted-stat calculations by ordered source membership."""
    weighted = regions._weighted_stats
    counts = Counter()

    def observe(items, context):
        key = tuple((int(item.get('qindex', -1)), float(item.get('count', 0))) for item in items)
        counts[key] += 1
        return weighted(items, context)

    with patch.object(regions, '_weighted_stats', side_effect=observe):
        yield counts


def dynamic_settings():
    return dict(max_colors=8, skip_white=True, lines=True, exact_available=True,
                color_fidelity='Faithful', profile_name='Microsoft Paint', source_palette=True)


def public_settings():
    result = plan_options()
    result.update(custom_color_workflow='Adaptive exact (recommended)',
                  exact_color_limit='8', exact_color_available=True,
                  color_fidelity='Faithful', color_layers='Off',
                  cpu_workers='1', cpu_workers_resolved=1, cpu_engine='Threads',
                  resource_scheduler='Off', ram_budget_mb=512, gpu_mode='CPU')
    return result


def membership_fixture():
    """Close red shades exercise in-place growth before forced color reduction."""
    colors = ((190, 48, 38), (198, 52, 40), (205, 55, 43), (255, 160, 132),
              (60, 12, 10), (30, 180, 60), (0, 50, 230), (230, 200, 30))
    counts = (600, 250, 200, 100, 50, 40, 30, 20)
    entries = [dict(qindex=i, rgb=color, count=count)
               for i, (color, count) in enumerate(zip(colors, counts))]
    total = sum(counts)
    context = {'grid_size': 2, 'stats': {
        i: regions.RegionColorStats(i, count, count / total,
            regions.oklab_metrics(color)[0], regions.dominant_hue_family(color),
            'midtone', .1, .1, 0., .5, (.5, .5, 0., 0.))
        for i, (color, count) in enumerate(zip(colors, counts))},
        'adjacency': {(i, i + 1): .3 for i in range(len(entries) - 1)}}
    return entries, context


class PreparedRegionApplicationTests(unittest.TestCase):
    def assert_prepared_once(self, counts):
        self.assertGreater(len(counts), 8, 'The real fixture must exercise merged region states')
        self.assertEqual(max(counts.values()), 1,
            f'Unchanged region statistics were rebuilt: {sum(counts.values())} calls '
            f'for {len(counts)} ordered membership states; worst={max(counts.values())}')

    def test_actual_dynamic_strokes_and_palette_reuse_unchanged_region_statistics(self):
        with closing(region_graphic()) as source:
            state = source.tobytes(), dict(source.info)
            for palette_only in (False, True):
                with self.subTest(palette_only=palette_only):
                    with preparation_counts() as counts:
                        builder = dynamic.build_dynamic_color_palette if palette_only else dynamic.build_dynamic_color_strokes
                        result = builder(source, PALETTE, **dynamic_settings())
                    self.assertTrue(result)
                    self.assertTrue(result[-1]['region_aware_quantization'])
                    self.assertGreater(result[-1]['region_quantization']['region_forced_merges'], 0)
                    self.assertEqual((source.tobytes(), source.info), state)
                    self.assert_prepared_once(counts)

    def test_actual_make_plan_reuses_region_statistics_and_preserves_borrowed_source(self):
        with calibrated(), closing(region_graphic()) as source:
            before = source.tobytes()
            with preparation_counts() as counts:
                plan = DrawBot.make_plan(source, source.size, public_settings())
            try:
                self.assertTrue(plan['options']['advanced_color_meta']['region_aware_quantization'])
                self.assertEqual(plan['options']['exact_color_limit_resolved'], 8)
                self.assertEqual(source.tobytes(), before)
                self.assert_prepared_once(counts)
            finally:
                close_plan(plan, source)

    def test_single_color_public_call_needs_no_pair_statistics(self):
        with closing(Image.new('RGB', (8, 6), PALETTE[2])) as source, preparation_counts() as counts:
            groups, colors, selectors, metadata = dynamic.build_dynamic_color_strokes(
                source, PALETTE, **dynamic_settings())
        self.assertEqual(colors, (PALETTE[2],))
        self.assertEqual(len(selectors), 1)
        self.assertEqual(sum(x1-x0+1 for group in groups for x0, _y0, x1, _y1 in group), 48)
        self.assertEqual(metadata['active_colors'], 1)
        self.assertFalse(counts)

    def test_growing_and_replaced_clusters_match_uncached_relation_at_every_decision(self):
        entries, context = membership_fixture()
        original = copy.deepcopy((entries, context))
        relation = regions.cluster_region_relation
        observed = {}
        in_place_growth = []
        forced = []

        def compare(a, b, ctx, **kwargs):
            actual = relation(a, b, ctx, **kwargs)
            self.assertEqual(actual, relation(a, b, ctx))
            for cluster in (a, b):
                if 'items' not in cluster:
                    continue
                identity = id(cluster)
                membership = tuple(item['qindex'] for item in cluster['items'])
                # Keep the object itself, so an id cannot be recycled after a
                # forced replacement and mistaken for in-place growth.
                if identity in observed and observed[identity][1] != membership:
                    in_place_growth.append(membership)
                observed[identity] = cluster, membership
            if 'items' in a and 'items' in b:
                forced.append(actual)
            return actual

        metadata = {}
        with patch.object(dynamic, 'cluster_region_relation', new=compare):
            result = dynamic._merge_quantized(entries, 2, region_context=context,
                                               diagnostics=metadata)
        expected_metadata = {}
        with patch.object(dynamic, 'cluster_region_relation',
                          new=lambda a, b, ctx, **_kw: relation(a, b, ctx)):
            expected = dynamic._merge_quantized(entries, 2, region_context=context,
                                                diagnostics=expected_metadata)
        self.assertTrue(in_place_growth)
        self.assertTrue(forced)
        self.assertGreater(metadata['region_forced_merges'], 0)
        self.assertEqual(result, expected)
        self.assertEqual(metadata, expected_metadata)
        self.assertEqual((entries, context), original)
        self.assertTrue(all(set(row) == {'items', 'rgb', 'count'} for row in result[0]))

    def test_changed_context_and_membership_are_fresh_on_the_next_operation(self):
        entries, context = membership_fixture()
        first = dynamic._merge_quantized(entries, 2, region_context=context)
        entries[0]['count'] = 7
        row = context['stats'][0]
        context['stats'][0] = replace(row, importance=1., protected_fraction=1.,
                                     tile_weights=(0., 0., 0., 1.))
        context['adjacency'] = {(0, 7): 1.}
        relation = regions.cluster_region_relation
        with patch.object(dynamic, 'cluster_region_relation',
                          new=lambda a, b, ctx, **_kw: relation(a, b, ctx)):
            expected = dynamic._merge_quantized(entries, 2, region_context=context)
        with preparation_counts() as counts:
            actual = dynamic._merge_quantized(entries, 2, region_context=context)
        self.assertNotEqual(first, expected)
        self.assertEqual(actual, expected)
        self.assertTrue(counts)
        self.assertEqual(max(counts.values()), 1)

    def test_absent_empty_and_partial_context_keep_the_uncached_defaults(self):
        entries, context = membership_fixture()
        relation = regions.cluster_region_relation
        for value in (None, {}, {'stats': {}},
                      {'stats': {0: context['stats'][0]}, 'grid_size': 2}):
            with self.subTest(context=value):
                with patch.object(dynamic, 'cluster_region_relation',
                                  new=lambda a, b, ctx, **_kw: relation(a, b, ctx)):
                    expected = dynamic._merge_quantized(entries, 3, region_context=value)
                actual = dynamic._merge_quantized(entries, 3, region_context=value)
                self.assertEqual(actual, expected)

    def test_stop_and_retained_error_release_prepared_tile_arrays(self):
        for outcome in ('stop', 'exception', 'relation_exception'):
            with self.subTest(outcome=outcome):
                entries, context = membership_fixture()
                original = copy.deepcopy((entries, context))
                tile_refs = []
                weighted = regions._weighted_stats
                relation = regions.cluster_region_relation
                stopped = [False]
                calls = [0]

                if outcome == 'relation_exception':
                    class FailedAdjacency(dict):
                        def get(self, key, default=0.):
                            if calls[0] >= 10:
                                raise RuntimeError('Retained adjacency error')
                            return super().get(key, default)
                    context['adjacency'] = FailedAdjacency(context['adjacency'])

                def observe(items, ctx):
                    result = weighted(items, ctx)
                    tile_refs.append(weakref.ref(result['tiles']))
                    return result

                def fail_or_stop(a, b, ctx, **kwargs):
                    calls[0] += 1
                    result = relation(a, b, ctx, **kwargs)
                    if calls[0] == 10:
                        if outcome == 'exception':
                            raise RuntimeError('Retained region relation error')
                        if outcome == 'stop':
                            stopped[0] = True
                    return result

                retained = None
                with patch.object(regions, '_weighted_stats', new=observe), \
                        patch.object(dynamic, 'cluster_region_relation', new=fail_or_stop):
                    try:
                        result = dynamic._merge_quantized(entries, 2,
                            cancelled=lambda: stopped[0], region_context=context)
                    except RuntimeError as error:
                        retained = error
                self.assertGreaterEqual(calls[0], 10)
                if outcome != 'stop':
                    self.assertIsNotNone(retained)
                    self.assertIsNotNone(retained.__traceback__)
                else:
                    self.assertEqual(result, (None, None))
                gc.collect()
                self.assertTrue(tile_refs)
                self.assertTrue(all(ref() is None for ref in tile_refs))
                self.assertEqual((entries, context), original)

    def test_actual_picture_palette_preparation_uses_the_same_operation_local_reuse(self):
        import PictureCustomPaletteLegacy as picture
        with closing(region_graphic()) as source, \
                patch.object(picture, 'load_cached_palette', return_value=None), \
                patch.object(picture, 'save_palette'), preparation_counts() as counts:
            state = source.tobytes(), dict(source.info)
            result = picture.build_picture_palette(source, PALETTE, max_colors=8,
                                                    calibration_fingerprint='batch19-test')
            self.assertEqual((source.tobytes(), source.info), state)
            self.assertTrue(result.colors)
            self.assert_prepared_once(counts)


if __name__ == '__main__':
    unittest.main()
