"""Regression cases reproduced during the 1.0.148 UI/input review."""
from contextlib import contextmanager
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import CalibrationAnchors as anchors
import CanvasDropPayload as drops
import ProfilePolish as polish
from PreviewDeck import PreviewDeck
from StartDrawingState import StartDrawingStateMachine
import UiCompatibility
import VersionHistory
import WordGuesser


class DropPayloadBatchTests(unittest.TestCase):
    def test_mixed_file_drop_reaches_the_first_supported_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = Path(tmp) / 'notes.txt'; text.write_text('notes')
            image = Path(tmp) / 'picture.png'; image.write_bytes(b'PNG fixture')
            result = drops.parse_canvas_drop('', split_items=(str(text), str(image)))
            self.assertEqual(result.source, str(image))
            self.assertEqual(result.kind, 'file')
            with self.assertRaisesRegex(ValueError, 'Drop an image file'):
                drops.parse_canvas_drop('', split_items=(str(text),))

    def test_oversized_drop_is_rejected_before_filesystem_or_regex_work(self):
        with patch.object(drops, 'MAX_DROP_CHARACTERS', 16), \
             patch.object(Path, 'is_file', side_effect=AssertionError('No filesystem probe')):
            with self.assertRaisesRegex(ValueError, 'too large'):
                drops.parse_canvas_drop('x' * 17)
        produced = []
        def endless_items():
            for i in range(1000):
                produced.append(i)
                yield f'image-{i}'
        with patch.object(drops, 'MAX_DROP_ITEMS', 2):
            with self.assertRaisesRegex(ValueError, 'at most'):
                drops.parse_canvas_drop('', split_items=endless_items())
        self.assertEqual(len(produced), 3)

    def test_localhost_file_urls_keep_local_path_and_reject_control_bytes(self):
        self.assertEqual(drops._file_uri_to_path('file://localhost/C:/pics/a.png'), 'C:/pics/a.png')
        self.assertEqual(drops._file_uri_to_path('file://localhost/tmp/a.png'), '/tmp/a.png')
        self.assertIsNone(drops._file_uri_to_path('file:///tmp/a%00.png'))


class PreviewDeckBatchTests(unittest.TestCase):
    def deck(self):
        deck = object.__new__(PreviewDeck)
        deck.pages = {'Original': Mock(), 'Result': Mock(), 'Safety': Mock()}
        deck.current = Mock()
        deck._visible_name = None
        return deck

    def test_selecting_same_page_does_not_relayout_or_hide_siblings(self):
        deck = self.deck()
        deck.set('Original'); deck.set('Original')
        deck.pages['Original'].pack.assert_called_once()
        for page in deck.pages.values():
            page.pack_forget.assert_not_called()
        # OptionMenu's variable can already contain Result here; it must not
        # suppress the actual visibility change.
        deck.current.get.return_value = 'Result'
        deck.set('Result')
        deck.pages['Original'].pack_forget.assert_called_once()
        deck.pages['Result'].pack.assert_called_once()
        deck.pages['Safety'].pack_forget.assert_not_called()

    def test_duplicate_or_blank_page_is_rejected_before_allocating_a_widget(self):
        deck = self.deck()
        with patch('PreviewDeck.ctk.CTkFrame', side_effect=AssertionError('No allocation')):
            for name in ('Original', '', '   ', None):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    deck.add(name)
        self.assertEqual(len(deck.pages), 3)

    def test_destroyed_scroll_target_does_not_raise_tcl_error(self):
        from customtkinter.windows.widgets.ctk_scrollable_frame import CTkScrollableFrame
        def broken(_self, _widget):
            raise tk.TclError('invalid command name: destroyed widget')
        with patch.object(UiCompatibility, '_PATCHED', False), \
             patch.object(CTkScrollableFrame, '_check_if_valid_scroll', broken):
            self.assertTrue(UiCompatibility.patch_customtkinter_scroll_guard())
            self.assertFalse(CTkScrollableFrame._check_if_valid_scroll(None, SimpleNamespace(master=None)))


class ProfilePolishBatchTests(unittest.TestCase):
    def test_builtin_lookup_does_not_allocate_a_discarded_generic_preset(self):
        with patch.object(polish, 'ProfileReleasePreset', side_effect=AssertionError('Unexpected constructor')):
            self.assertEqual(polish.profile_release_preset('Gartic Phone').profile_key, 'gartic-phone')

    def test_shared_defaults_cannot_be_modified_by_a_caller(self):
        preset = polish.profile_release_preset('Microsoft Paint')
        before = polish.final_profile_defaults('Microsoft Paint')
        with self.assertRaises(TypeError):
            preset.default_overrides['speed'] = 'untrusted'
        exported = preset.as_dict()
        exported['default_overrides']['speed'] = 'local edit'
        self.assertEqual(polish.final_profile_defaults('Microsoft Paint'), before)

    def test_invalid_and_explicit_empty_calibration_metadata_are_handled(self):
        for malformed in ('estimated', ['estimated'], True, 1):
            self.assertIsInstance(polish.profile_release_warnings('Gartic Phone', malformed), tuple)
        _options, metadata = polish.apply_profile_polish(
            'Other drawing app', {'calibration_state': {'palette_state': 'estimated'}}, calibration_state={})
        self.assertFalse(any('Palette is not verified' in value for value in metadata['warnings']))

    def test_single_warning_string_is_not_rendered_as_individual_characters(self):
        metadata = {'preset_name': 'Example', 'warnings': 'A real warning'}
        self.assertIn('1 warning(s)', polish.format_profile_polish(metadata))
        self.assertIn('- A real warning', polish.format_profile_polish(metadata, compact=False))


class StartStateBatchTests(unittest.TestCase):
    def test_repeated_state_updates_keep_elapsed_time_and_bounded_history(self):
        now = [0.0]
        machine = StartDrawingStateMachine(clock=lambda: now[0])
        now[0] = 3.0
        machine.transition('START_ACCEPTED', 'still waiting')
        self.assertEqual(machine.snapshot().elapsed_in_state, 3.0)
        self.assertTrue(machine.stalled(2.0))
        self.assertEqual(len(machine.history), 1)
        machine.transition('PREFLIGHT')
        self.assertEqual(machine.snapshot().elapsed_in_state, 0.0)

    def test_watchdog_uses_one_consistent_clock_snapshot(self):
        values = iter((0.0, 1.9, 2.1))
        machine = StartDrawingStateMachine(clock=lambda: next(values))
        self.assertEqual(machine.watchdog_text(2.0), '')
        self.assertIn('2.1s', machine.watchdog_text(2.0))

    def test_logging_failure_cannot_break_or_skip_state_transitions(self):
        machine = StartDrawingStateMachine(logger=Mock(side_effect=OSError('disk full')))
        machine.transition('PREFLIGHT')
        with self.assertRaises(ValueError):
            machine.transition('INPUT_ARMED')
        self.assertEqual(machine.state, 'PREFLIGHT')


class CalibrationAnchorBatchTests(unittest.TestCase):
    def test_schema_requires_an_integer_and_coordinates_fit_windows_long(self):
        for schema in (True, 1.0, '1'):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                anchors.validate_anchor({'version': schema, 'client_rect': [0, 0, 100, 100]})
        for rect in ((0, 0, 2 ** 31, 100), (-(2 ** 31) - 1, 0, 10, 10)):
            with self.assertRaises(ValueError):
                anchors.make_anchor(rect)

    def test_translated_points_cannot_overflow_native_coordinates(self):
        anchor = anchors.make_anchor((0, 0, 100, 100))
        current = (50, 50, 150, 150)
        for resolver, value in ((anchors.resolve_point, (2 ** 31 - 20, 4)),
                                (anchors.resolve_points, [(2 ** 31 - 20, 4)])):
            with self.assertRaises(ValueError): resolver(value, anchor, current)
        self.assertEqual(anchors.resolve_point((-100, 10), anchor, (-50, -20, 50, 80)), (-150, -10))

    def test_invalid_layout_tolerance_fails_as_validation_error(self):
        anchor = anchors.make_anchor((0, 0, 100, 100))
        for tolerance in (-1, True, 2.9, float('inf'), '3'):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                anchors.ensure_same_layout(anchor, (0, 0, 100, 100), tolerance)


class LocalTextBatchTests(unittest.TestCase):
    def test_word_list_read_is_bounded_even_if_the_file_size_changes(self):
        stream = io.BytesIO(b'apple\nbanana\n')
        with patch.object(WordGuesser, 'MAX_WORD_LIST_BYTES', 5), \
             patch.object(Path, 'open', return_value=stream):
            with self.assertRaisesRegex(ValueError, 'at most 2 MB'):
                WordGuesser.load_words(Path('growing.txt'))

    def test_word_length_index_preserves_patterns_and_mutable_dictionary_updates(self):
        words = ['katt', 'kort', 'kotte', 'ko', 'röd bil', 'katt']
        WordGuesser._word_buckets.cache_clear()
        self.assertEqual(WordGuesser.find_candidates(words, 'k__t', '4'), ['katt', 'kort'])
        self.assertEqual(WordGuesser.find_candidates(words, 'r_d b_l', '6'), ['röd bil'])
        self.assertEqual(WordGuesser.find_candidates(words, '', '2'), ['ko'])
        self.assertGreaterEqual(WordGuesser._word_buckets.cache_info().hits, 2)
        words.append('kost')
        self.assertEqual(WordGuesser.find_candidates(words, 'k__t', '4'), ['katt', 'kort', 'kost'])

    def test_history_reads_only_the_viewer_budget_and_tries_readable_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'docs').mkdir()
            primary = root / 'VERSION-HISTORY.md'; primary.write_text('x' * 500)
            fallback = root / 'docs' / 'VERSION-HISTORY.md'; fallback.write_text('fallback history')
            original = Path.open
            reads = []
            @contextmanager
            def bounded(path, *args, **kwargs):
                with original(path, *args, **kwargs) as stream:
                    def read(size):
                        reads.append(size)
                        self.assertLessEqual(size, 11)
                        return stream.read(size)
                    yield SimpleNamespace(read=read)
            with patch.object(VersionHistory, 'candidate_roots', return_value=(root,)), patch.object(Path, 'open', bounded):
                self.assertIn('truncated', VersionHistory.read_version_history(10))
            self.assertEqual(reads, [11])
            def denied(path, *args, **kwargs):
                if path == primary: raise PermissionError('locked primary history')
                return original(path, *args, **kwargs)
            with patch.object(VersionHistory, 'candidate_roots', return_value=(root,)), patch.object(Path, 'open', denied):
                self.assertEqual(VersionHistory.read_version_history(), 'fallback history\n')


if __name__ == '__main__': unittest.main()
