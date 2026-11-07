import unittest
from CanvasGuard import CanvasGuard
from Precision import CanvasTransform
from SafeFillMask import (
    filter_fill_regions_by_source_mask,
    filter_fill_regions_by_runtime_mask,
    source_fill_margin_px,
    choose_safe_background_seed,
)
from Version import APP_VERSION, FILE_VERSION


class SafeFillMaskIntegrationTests(unittest.TestCase):
    def test_version_metadata_v1052(self):
        assert APP_VERSION == '1.0.148'
        assert FILE_VERSION == '1.0.148'


    def test_source_fill_mask_rejects_edge_region(self):
        regions = [
            {'color_index': 1, 'bbox': (1, 10, 20, 25), 'seed_pixel': (10, 15), 'row_spans': ((15, 1, 20),)},
            {'color_index': 2, 'bbox': (8, 10, 22, 25), 'seed_pixel': (12, 15), 'row_spans': ((15, 8, 22),)},
        ]
        accepted, meta = filter_fill_regions_by_source_mask(regions, (40, 40), margin_px=4)
        assert len(accepted) == 1
        assert accepted[0]['color_index'] == 2
        assert meta['rejected_regions'] == 1
        assert meta['rejected']['outside safe fill mask'] == 1


    def test_source_fill_mask_rejects_contour_outside_safe_mask(self):
        regions = [{'color_index': 1, 'bbox': (5, 5, 20, 20), 'seed_pixel': (10, 10),
                    'contour': ((5, 5), (20, 5), (20, 20), (5, 20), (5, 5)),
                    'row_spans': ((10, 5, 20),)}]
        accepted, meta = filter_fill_regions_by_source_mask(regions, (40, 40), margin_px=6)
        assert accepted == []
        assert meta['rejected']['outside safe fill mask'] == 1


    def test_background_seed_candidates_are_inside_safe_mask(self):
        candidates = choose_safe_background_seed([(1, 1), (3, 3), (18, 18)], (20, 20), 4)
        assert (1, 1) not in candidates
        assert (3, 3) not in candidates
        assert (18, 18) not in candidates
        assert candidates
        assert all(4 <= x <= 15 and 4 <= y <= 15 for x, y in candidates)


    def test_runtime_fill_mask_rejects_without_clamping(self):
        guard = CanvasGuard.from_area((100, 100, 50, 50), brush_px=5, edge_margin_px=2)
        transform = CanvasTransform(50, 50, (50, 50), 100, 100)
        regions = [
            {'color_index': 1, 'bbox': (0, 0, 8, 8), 'seed_pixel': (2, 2), 'row_spans': ((2, 0, 8),)},
            {'color_index': 2, 'bbox': (10, 10, 20, 20), 'seed_pixel': (15, 15), 'row_spans': ((15, 10, 20),)},
        ]
        result = filter_fill_regions_by_runtime_mask(regions, (50, 50), transform, guard)
        assert result.rejected_regions == 1
        assert len(result.accepted_regions) == 1
        assert result.accepted_regions[0]['color_index'] == 2


    def test_margin_tracks_brush_size(self):
        assert source_fill_margin_px(3, 2, (100, 100)) >= 4
        assert source_fill_margin_px(13, 2, (100, 100)) > source_fill_margin_px(3, 2, (100, 100))



if __name__ == "__main__":
    unittest.main()
