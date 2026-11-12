"""Bound exact comparison scratch using existing, committed recording inputs."""
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from ScreenRecording import append_recorded_frame


ASSET = Path(__file__).with_name('golden-regression') / 'small-detail-preservation.png'


class RecordingComparisonTests(unittest.TestCase):
    def image(self, mode='P', size=(800, 500)):
        with Image.open(ASSET) as source, source.resize(size) as resized:
            image = resized.convert(mode)
        self.addCleanup(image.close)
        return image

    def copy(self, source):
        image = source.copy()
        self.addCleanup(image.close)
        return image

    def test_full_public_comparison_matches_historical_bytes_for_every_recording_mode(self):
        for mode in ('P', 'RGB', 'RGBA', 'L', 'LA', '1', 'I', 'F'):
            for size in ((17, 19), (803, 501)):
                with self.subTest(mode=mode, size=size):
                    previous = self.image(mode, size)
                    frame = self.copy(previous)
                    reference = previous.tobytes()
                    frames, durations = [previous], [250.25]
                    self.assertEqual(reference, frame.tobytes())
                    self.assertFalse(append_recorded_frame(frames, durations, frame, 249.75))
                    self.assertEqual(durations, [500.0])
                    self.assertIs(frames[0], previous)
                    self.assertEqual(previous.tobytes(), reference)
                    self.assertEqual(frame.tobytes(), reference)

    def test_actual_recording_size_never_exports_a_full_frame_and_stops_at_first_difference(self):
        previous = self.image()
        for location in (None, (0, 0), (799, 499)):
            with self.subTest(location=location):
                frame = self.copy(previous)
                if location is not None:
                    frame.putpixel(location, (frame.getpixel(location) + 1) % 256)
                expected = previous.tobytes() != frame.tobytes()
                exports = []
                original = Image.Image.tobytes
                def exported(image, *args, **kwargs):
                    exports.append(image.size)
                    return original(image, *args, **kwargs)
                frames, durations = [previous], [250]
                with patch.object(Image.Image, 'tobytes', new=exported):
                    self.assertEqual(append_recorded_frame(frames, durations, frame, 250), expected)
                self.assertTrue(exports)
                self.assertTrue(all(width * height <= 65536 for width, height in exports))
                self.assertEqual(durations, [250, 250] if expected else [500])
                self.assertEqual(len(exports), 2 if location == (0, 0) else 14)
                previous.getpixel((0, 0)); frame.getpixel((0, 0))

    def test_palette_transparency_size_and_mode_mismatch_do_not_read_raster_storage(self):
        previous = self.image()
        changed_palette = self.copy(previous)
        palette = changed_palette.getpalette()
        palette[0] = (palette[0] + 1) % 256
        changed_palette.putpalette(palette)
        changed_transparency = self.copy(previous)
        changed_transparency.info['transparency'] = 0
        different_size = self.image(size=(799, 500))
        different_mode = self.image(mode='RGB')
        for frame in (changed_palette, changed_transparency, different_size, different_mode):
            with self.subTest(mode=frame.mode, size=frame.size):
                frames, durations = [previous], [250]
                with patch.object(Image.Image, 'tobytes', side_effect=AssertionError('unnecessary raster export')):
                    self.assertTrue(append_recorded_frame(frames, durations, frame, 250))
                self.assertEqual(frames, [previous, frame])
                self.assertEqual(durations, [250, 250])

    def test_small_frame_keeps_its_no_crop_path(self):
        previous = self.image(size=(256, 256))
        frame = self.copy(previous)
        with patch.object(Image.Image, 'crop', side_effect=AssertionError('small frame cropped')):
            self.assertFalse(append_recorded_frame([previous], [250], frame, 250))

    def test_failed_export_or_second_crop_closes_only_private_strips(self):
        for failure in ('export', 'second_crop'):
            with self.subTest(failure=failure):
                previous = self.image()
                frame = self.copy(previous)
                originals = (previous.tobytes(), frame.tobytes())
                crops = []
                original_crop = Image.Image.crop
                original_bytes = Image.Image.tobytes
                def crop(image, box=None):
                    if failure == 'second_crop' and crops:
                        raise MemoryError('strip crop failed')
                    result = original_crop(image, box)
                    crops.append(result)
                    return result
                def exported(image, *args, **kwargs):
                    if failure == 'export':
                        raise OSError('strip export failed')
                    return original_bytes(image, *args, **kwargs)
                frames, durations = [previous], [250]
                retained_error = None
                with ExitStack() as stack:
                    stack.enter_context(patch.object(Image.Image, 'crop', new=crop))
                    stack.enter_context(patch.object(Image.Image, 'tobytes', new=exported))
                    try:
                        append_recorded_frame(frames, durations, frame, 250)
                    except (MemoryError, OSError) as error:
                        retained_error = error
                self.assertIsNotNone(retained_error)
                self.assertEqual(frames, [previous]); self.assertEqual(durations, [250])
                self.assertEqual((previous.tobytes(), frame.tobytes()), originals)
                self.assertTrue(crops)
                for image in crops:
                    with self.assertRaises(ValueError): image.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
