import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveDeadlineRenderer as ADR
import DetailZoomPass as DZ
import FastDryRun as FDR
import GarticSketchPaths as GSP
import HybridRenderer3 as HR
import PixelAccuratePlanner as PAP
import PixelStrokeEngine as PSE
import PortraitPlanner as PP
import Sketch2Planner as SK2
import StrokeOptimizer as SO
from ExecutionCostModel import build_cost_model
from RasterIdentity import canonical_pixels_from_paths, compare_runs_to_paths


class DetailZoomBoundaryTests(unittest.TestCase):
    def test_size_limit_is_checked_before_converting_large_source(self):
        for mode, width in (('2x', 751), ('4x', 901)):
            image = Image.new('RGB', (width, 3))
            with patch.object(DZ, '_visible_rgb', side_effect=AssertionError('converted oversized zoom')):
                *_, meta = DZ.add_detail_zoom_pass(image, image, [(0, 0, 0)], [[]], [[]], [], {'detail_zoom': mode})
            self.assertFalse(meta['enabled'])
            self.assertEqual(meta['factor'], 1)
        observed = []
        def cells(zoom, base, factor, **kwargs):
            observed.append(zoom.shape)
            return np.zeros(base.shape[:2], np.float32), np.zeros(base.shape[:2], np.float32)
        image = Image.new('RGB', (900, 3))
        with patch.object(DZ, '_candidate_cells', side_effect=cells):
            DZ.add_detail_zoom_pass(image, image, [(0, 0, 0)], [[]], [[]], [], {'detail_zoom': '4x'})
        self.assertEqual(observed, [(6, 1800, 3)])

    def test_shortlist_preserves_full_stable_nonmaximum_suppression_order(self):
        def reference(score, cap, threshold):
            width = score.shape[1]
            ranked = sorted((float(score[y, x]), y * width + x) for y, x in np.ndindex(score.shape)
                            if score[y, x] >= threshold)
            ranked.sort(key=lambda pair: (-pair[0], pair[1]))
            blocked = set()
            output = []
            for value, index in ranked:
                y, x = divmod(index, width)
                if (x, y) in blocked:
                    continue
                output.append((x, y, value))
                blocked.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                if len(output) >= 2 * cap:
                    break
            return output
        rng = np.random.default_rng(148)
        scores = [rng.integers(0, 10, (27, 29)).astype(np.float32),
                  np.full((24, 28), 7, np.float32), rng.uniform(0, 30, (31, 33)).astype(np.float32)]
        for score in scores:
            for cap in (1, 2, 7, 100):
                self.assertEqual(DZ._pick_cells(score, cap, threshold=4), reference(score, cap, 4))

    def test_only_verified_brush_ladder_is_used_for_detail(self):
        plan = {'nominal_sizes': [1, 4, 8], 'control_positions': [(1, 1), (2, 2), (3, 3)],
                'target_position': (2, 2), 'confidence': .9, 'verified_sizes': [4, 8], 'safe_guard_px': 8}
        self.assertEqual(DZ._smallest_runtime_brush({'brush_px': 4, 'browser_brush_plan': plan}), 4)
        partial = {'nominal_sizes': [1, 4], 'confidence': .9}
        self.assertEqual(DZ._smallest_runtime_brush({'brush_px': 4, 'browser_brush_plan': partial}), 4)
        self.assertEqual(DZ._smallest_runtime_brush({'brush_px': 4, 'profile_key': 'microsoft-paint',
                                                   'effective_paint_tool': 'Pencil'}), 1)


class CostStateTests(unittest.TestCase):
    def model(self):
        return build_cost_model({'profile_key': 'microsoft-paint', 'brush_px': 1,
                                 '_execution_cost_calibration_override': {'samples': 0}}, (20, 20), (20, 20))

    def test_empty_paths_do_not_change_state_or_cost_palette(self):
        model = self.model()
        empty = model.sequence_cost([{'path': (), 'color_index': 2, 'brush_px': 8}], initial_brush=1)
        self.assertEqual(empty.total_seconds, 0.0)
        self.assertEqual(empty.palette_switches, 0)
        self.assertEqual(empty.brush_switches, 0)
        actual = [{'path': ((1, 1), (5, 1)), 'color_index': 3}]
        self.assertEqual(model.sequence_cost([{'path': (), 'color_index': 7}] + actual), model.sequence_cost(actual))
        # Explicit UI operations still count even though they have no path.
        self.assertGreater(model.sequence_cost([{'operation_type': 'palette_change', 'color_index': 2}]).total_seconds, 0)

    def test_empty_deadline_paths_do_not_become_billable_dots(self):
        image = Image.new('RGB', (20, 20))
        options = {'time_budget_mode': 'Custom', 'manual_max_seconds': 60, 'paint_profile': True,
                   'speed': 'Balanced', 'delay': .006}
        with patch.object(ADR, 'build_importance_map', return_value=(np.zeros((20, 20), np.float32), {})):
            with patch.object(ADR, '_calibration_guard', return_value=(0, {'ratio': 1})):
                groups, sequence, meta, _ = ADR.adapt_execution_plan(image, (20, 20), [[()], []], options)
        self.assertEqual(groups, [[], []])
        self.assertEqual(sequence, [])
        self.assertEqual(meta['source_paths'], 0)
        self.assertEqual(meta['fixed_overhead']['palette_seconds'], 0)

    def test_implicit_brush_uses_explicit_or_initial_current_state(self):
        model = self.model()
        path = ((1, 1), (10, 1))
        sequence = [{'operation_type': 'brush_change', 'brush_px': 8}, {'path': path}]
        implicit = model.sequence_cost(sequence, initial_brush=1)
        explicit = model.sequence_cost([sequence[0], {'path': path, 'brush_px': 8}], initial_brush=1)
        self.assertEqual(implicit, explicit)
        self.assertEqual(implicit.brush_switches, 1)
        self.assertEqual(model.sequence_cost([{'path': path}], initial_brush=8).brush_switches, 0)

    def test_component_candidate_cost_is_evaluated_once_per_order(self):
        model = self.model()
        comp = PSE.Component(0, 0, area=12, bbox=(0, 0, 3, 2),
                             horizontal_runs=[(0, y, 3, y) for y in range(3)],
                             vertical_runs=[(x, 0, x, 2) for x in range(4)])
        with patch.object(model, 'paths_seconds', wraps=model.paths_seconds) as costs:
            paths, meta = PSE.build_component_paths(comp, np.zeros((3, 4), np.int32), cost_model=model)
        self.assertEqual(costs.call_count, 4)
        self.assertTrue(compare_runs_to_paths(comp.horizontal_runs, paths).safe)
        self.assertAlmostEqual(meta['candidates'][comp.orientation]['estimated_seconds'], model.paths_seconds(paths), places=6)


class PlannerReuseTests(unittest.TestCase):
    def test_repeated_color_order_cannot_duplicate_dry_run_accounting(self):
        plan = {'groups': [[(x, color, x + 1, color) for x in range(8)] for color in range(2)],
                'count': 16, 'options': {'color_order': [0, 0, 'bad', 1, 1, 99]}}
        result = FDR.sample_plan(plan, max_colors=4, max_paths=8)
        self.assertEqual(result['options']['color_order'], [0, 1])
        self.assertEqual(result['count'], sum(map(len, result['groups'])))
        self.assertEqual(result['options']['dry_run_total_colors'], 2)

    def test_shared_endpoint_cursor_preserves_stable_graph_chains(self):
        def reference(paths):
            remaining = {index: path for index, path in enumerate(paths)}
            output = []; joins = 0
            while remaining:
                seed = min(remaining)
                chain = list(remaining.pop(seed))
                while True:
                    endpoint = chain[-1]
                    candidates = [index for index, path in remaining.items() if endpoint in (path[0], path[-1])]
                    if not candidates:
                        break
                    path = remaining.pop(min(candidates))
                    if path[0] != endpoint:
                        path = tuple(reversed(path))
                    chain.extend(path[1:]); joins += 1
                output.append(tuple(chain))
            return output, joins
        rng = random.Random(148)
        for _ in range(30):
            paths = []
            for _ in range(80):
                a, b = (rng.randrange(5), rng.randrange(5)), (rng.randrange(5), rng.randrange(5))
                paths.append((a,) if a == b else (a, b))
            self.assertEqual(SO._merge_exact_graph(paths), reference(paths))
        self.assertEqual(SO._merge_exact_graph([((0, 0),)] * 10000), ([((0, 0),)], 9999))

    def test_dense_gartic_component_reuses_exact_vertical_raster(self):
        image = Image.new('L', (40, 24), 0)
        with patch.object(GSP, 'verticalize_horizontal_runs', wraps=GSP.verticalize_horizontal_runs) as vertical:
            paths, _ = GSP.trace_contours(image, options={'_execution_cost_calibration_override': {'samples': 0}})
        self.assertEqual(vertical.call_count, 1)
        self.assertEqual(canonical_pixels_from_paths(paths), frozenset((x, y) for y in range(24) for x in range(40)))

    def test_picture_palette_legacy_adapter_keeps_shape_checks(self):
        adapter = SimpleNamespace(height=1, palette_index=np.array([[0, 1]], dtype=np.int16),
                                  drawable_mask=np.array([[True, True]]))
        self.assertEqual(PAP.groups_from_pixel_map(adapter, 2), [[(0, 0, 0, 0)], [(1, 0, 1, 0)]])
        adapter.drawable_mask = np.array([[True]])
        with self.assertRaises(ValueError):
            PAP.groups_from_pixel_map(adapter, 2)


class PortraitLifecycleTests(unittest.TestCase):
    def info(self):
        return SimpleNamespace(accelerated=False, as_dict=lambda: {'accelerated': False, 'backend': 'CPU'})

    def test_precancelled_portrait_preparation_does_not_allocate_or_probe(self):
        image = Image.new('RGB', (30, 30))
        with patch.object(PP.ImageOps, 'exif_transpose', side_effect=AssertionError('allocated cancelled image')):
            with self.assertRaises(InterruptedError):
                PP.prepare_portrait_image(image, (100, 100), 8, cancelled=lambda: True)

    def test_cpu_local_contrast_can_cancel_within_work(self):
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 2
        with self.assertRaises(InterruptedError):
            PP._enhance_local_contrast(Image.new('L', (100, 100)), .4, cancelled=cancelled)
        self.assertEqual(calls, 2)

    def test_session_released_on_dot_success_line_failure_and_cancellation(self):
        gray = Image.new('L', (4, 4), 0)
        for outcome in ('dot', 'failure', 'cancel'):
            session = object(); metadata = {'_gpu_session': session}
            with patch.object(PP, 'gpu_release_analysis_session') as release:
                if outcome == 'dot':
                    groups, _ = PP.portrait_strokes(gray, lines=False, acceleration_meta=metadata)
                    self.assertTrue(groups[0])
                elif outcome == 'failure':
                    with patch.object(PP, '_saliency_map', side_effect=RuntimeError('test planning failure')):
                        with self.assertRaisesRegex(RuntimeError, 'test planning failure'):
                            PP.portrait_strokes(gray, acceleration_meta=metadata)
                else:
                    with self.assertRaises(InterruptedError):
                        PP.portrait_strokes(gray, acceleration_meta=metadata, cancelled=lambda: True)
                release.assert_called_once_with(session, trim_cache=True)
            self.assertNotIn('_gpu_session', metadata)

    def test_preparation_session_cleanup_tracks_ownership_and_late_cancel(self):
        image = Image.new('RGB', (4, 4)); session = object(); stopped = False
        def enhanced(gray, *args):
            nonlocal stopped
            stopped = True
            return gray, self.info(), session
        metadata = {}
        with patch.object(PP, 'gpu_enhance_portrait', side_effect=enhanced):
            with patch.object(PP, 'gpu_release_analysis_session') as release:
                with self.assertRaises(InterruptedError):
                    PP.prepare_portrait_image(image, (10, 10), 8, acceleration_meta=metadata, cancelled=lambda: stopped)
                release.assert_called_once_with(session, trim_cache=True)
        self.assertNotIn('_gpu_session', metadata)
        with patch.object(PP, 'gpu_enhance_portrait', return_value=(Image.new('L', (4, 4)), self.info(), session)):
            with patch.object(PP, 'gpu_release_analysis_session') as release:
                PP.prepare_portrait_image(image, (10, 10), 8)
                release.assert_called_once_with(session, trim_cache=True)
            with patch.object(PP, 'gpu_release_analysis_session') as release:
                PP.prepare_portrait_image(image, (10, 10), 8, acceleration_meta=metadata)
                release.assert_not_called()
                self.assertIs(metadata['_gpu_session'], session)


class StructureAnalysisTests(unittest.TestCase):
    def test_white_black_and_primary_luminance_do_not_overflow(self):
        pixels = np.zeros((4, 4, 3), dtype=np.uint8); pixels[:, 2:] = 255
        result = HR.analyze_source(Image.fromarray(pixels))
        self.assertAlmostEqual(result.luminance_std, .5)
        self.assertAlmostEqual(result.edge_density, 4 / 24)
        self.assertAlmostEqual(result.mean_gradient, 4 / 24)
        primary = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]]], np.uint8)
        expected = np.array([sum(int(channel) * weight for channel, weight in zip(rgb, (54, 183, 19))) / 256
                             for rgb in primary[0]])
        result = HR.analyze_source(Image.fromarray(primary))
        self.assertAlmostEqual(result.luminance_std, np.std(expected) / 255)
        self.assertAlmostEqual(result.mean_gradient, np.mean(np.abs(np.diff(expected))) / 255)

    def test_sketch_structure_rejects_size_and_cancellation_before_conversion(self):
        with patch.object(SK2, '_flatten', side_effect=AssertionError('allocated before gate')):
            with self.assertRaises(InterruptedError):
                SK2.structure_map(Image.new('RGB', (8, 8)), cancelled=lambda: True)
            with self.assertRaises(ValueError):
                SK2.structure_map(Image.new('RGB', (1501, 1)))

    def test_sketch_cancels_inside_one_connected_component(self):
        mask = np.ones((60, 60), dtype=np.bool_)
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaises(InterruptedError):
            SK2._filter_components(mask, mask.astype(np.float32), 1, min_component=2,
                                   protect_factor=1, cancelled=cancelled)
        self.assertEqual(calls, 3)


if __name__ == '__main__':
    unittest.main()
