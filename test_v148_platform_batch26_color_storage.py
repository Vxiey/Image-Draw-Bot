"""Actual palette/cache readers and controller saves share storage contracts."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import CalibrationState
import ColorCache
import Colors
import DrawBot
import ExactColorTools
import GetColorPositions
import PixelData
import ProfileStorage
import RuntimePaths
from CalibrationAnchors import make_anchor


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ColorStorageFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.palette = self.root / 'calibration.json'
        self.saved_colors = [(color, dict(vars(color))) for color in Colors.allColors]
        self.addCleanup(self.restore_palette)
        self.stack.enter_context(patch.object(ProfileStorage, 'data_dir', return_value=self.root))
        self.stack.enter_context(patch.object(ExactColorTools, 'data_dir', return_value=self.root))

    def restore_palette(self):
        for color, attributes in self.saved_colors:
            vars(color).clear()
            vars(color).update(attributes)
        Colors.allColors[:] = [color for color, _attributes in self.saved_colors]
        PixelData.closest_color.cache_clear()

    def palette_state(self):
        return [(id(color), dict(vars(color))) for color in Colors.allColors]

    def payload(self, profile='generic', version=4):
        data = {
            'version': version, 'profile': profile, 'state': 'verified',
            'colors': [
                {'name': 'Röd', 'position': [-90, -40], 'argb': [128, 255, 0, 0], 'game_index': 0},
                {'name': 'Ink', 'position': [-50, -30], 'rgb': [1, 2, 3], 'game_index': 1},
            ],
            'verification': {'method': 'local-fixture', 'confidence': .95,
                             'extra': {'description': 'Återläst metadata', 'values': [1, True, None]}},
        }
        if version == 4:
            data['anchor'] = make_anchor((-100, -50, 500, 350))
        return data

    def write_payload(self, data, path=None):
        path = self.palette if path is None else path
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path.read_bytes()

    def broken_documents(self, profile='generic'):
        text = json.dumps(self.payload(profile))
        return {
            'duplicate-profile': text.replace('"profile": ' + json.dumps(profile),
                '"profile": "different-profile", "profile": ' + json.dumps(profile), 1),
            'duplicate-position': text.replace('"position": [-90, -40]',
                '"position": [20, 30], "position": [-90, -40]', 1),
            'very-deep-document': text[:-1] + ', "extra": ' + '[' * 2000 + '0' + ']' * 2000 + '}',
            'bounded-depth': text[:-1] + ', "extra": ' + '[' * 40 + '0' + ']' * 40 + '}',
            'nonfinite': text[:-1] + ', "extra": NaN}',
        }

    def app(self, profile='Other drawing app'):
        return SimpleNamespace(game=Value(profile), paint_simple=Value(False),
            paint_tool=Value('Use current tool'), calibration_path=self.palette,
            palette_ready=False, palette_text=Value('previous label'))

    @contextmanager
    def observe_reads(self, target):
        """Observe real file reads, replacing no bytes, decoder or consumer."""
        original = Path.open
        observations = []

        class FileReadObserver:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def read(self, size=-1):
                value = self.stream.read(size)
                observations.append((size, len(value)))
                return value

        def opening(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return FileReadObserver(stream) if path == target else stream

        with patch.object(Path, 'open', new=opening):
            yield observations


class PaletteReaderFlowTests(ColorStorageFixture):
    def test_actual_refresh_palette_recovers_from_ambiguous_and_deep_documents(self):
        for profile in ('Other drawing app', 'Skribbl.io'):
            app = self.app(profile)
            key = DrawBot.PROFILES[profile][0]
            for label, text in self.broken_documents(key).items():
                with self.subTest(profile=profile, document=label):
                    self.palette.write_text(text, encoding='utf-8')
                    before = self.palette.read_bytes()
                    DrawBot.DrawBotApp.refresh_palette(app)
                    self.assertFalse(app.palette_ready)
                    self.assertIn('Estimated palette' if profile == 'Skribbl.io' else
                                  'Calibration unavailable', app.palette_text.get())
                    self.assertEqual(self.palette.read_bytes(), before)
            self.write_payload(self.payload(key))
            DrawBot.DrawBotApp.refresh_palette(app)
            self.assertTrue(app.palette_ready)
            self.assertIn('Palette verified', app.palette_text.get())
            self.assertEqual([color.RGB for color in Colors.allColors], [(255, 127, 127), (1, 2, 3)])

    def test_invalid_json_is_rejected_before_any_global_palette_mutation(self):
        for label, text in self.broken_documents().items():
            for consumer in (Colors.load_calibration, Colors.calibration_metadata):
                with self.subTest(document=label, consumer=consumer.__name__):
                    self.write_payload(self.payload())
                    Colors.load_calibration(self.palette, profile_key='generic')
                    before = self.palette_state()
                    self.palette.write_text(text, encoding='utf-8')
                    raw = self.palette.read_bytes()
                    failure = None
                    try:
                        consumer(self.palette, profile_key='generic')
                    except Exception as error:
                        failure = error
                    with self.subTest(boundary='controlled-rejection'):
                        self.assertIsInstance(failure, ValueError)
                    with self.subTest(boundary='unchanged-global-palette'):
                        self.assertEqual(self.palette_state(), before)
                    self.assertEqual(self.palette.read_bytes(), raw)

    def test_supported_versions_metadata_argb_and_anchor_translation_are_preserved(self):
        for version in (1, 2, 3, 4):
            with self.subTest(version=version):
                data = self.payload(version=version)
                self.write_payload(data)
                before = self.palette_state()
                meta = Colors.calibration_metadata(self.palette, profile_key='generic')
                self.assertEqual(meta, {'version': version, 'anchor': data.get('anchor'),
                    'profile': 'generic', 'state': 'verified',
                    'verification': data['verification'], 'count': 2})
                self.assertEqual(self.palette_state(), before)
                result = Colors.load_calibration(self.palette, profile_key='generic',
                    current_client_rect=(-80, -20, 520, 380))
                self.assertEqual(result, {'anchor': data.get('anchor'), 'count': 2})
                positions = [(-70, -10), (-30, 0)] if version == 4 else [(-90, -40), (-50, -30)]
                self.assertEqual([(color.name, (color.x, color.y), color.RGB) for color in Colors.allColors],
                    [('Röd', positions[0], (255, 127, 127)), ('Ink', positions[1], (1, 2, 3))])
                self.assertEqual(json.loads(self.palette.read_text(encoding='utf-8')), data)
                before = self.palette_state()
                with self.assertRaises(ValueError):
                    Colors.load_calibration(self.palette, profile_key='different-profile')
                self.assertEqual(self.palette_state(), before)
                if version < 4:
                    with self.assertRaisesRegex(ValueError, 'fixed screen coordinates'):
                        Colors.load_calibration(self.palette, require_anchor=True)
                    self.assertEqual(self.palette_state(), before)
        missing = self.root / 'not-created.json'
        self.assertEqual(Colors.calibration_metadata(missing), {'version': 0, 'anchor': None})
        with self.assertRaises(FileNotFoundError):
            Colors.load_calibration(missing)

    def test_legacy_position_and_palette_fallback_stays_atomic_and_invalidates_color_lookup(self):
        Colors.reset_palette()
        positions = self.root / 'positions.txt'
        old_palette = self.root / 'palette.json'
        coordinates = [(10 + index * 3, 20) for index in range(len(Colors.allColors))]
        positions.write_text(''.join(f'{x}\n{y}\n' for x, y in coordinates), encoding='utf-8')
        values = [list(color.RGB) for color in Colors.allColors]
        values[0], values[3] = values[3], values[0]
        old_palette.write_text(json.dumps(values), encoding='utf-8')
        self.assertEqual(PixelData.closest_color((0, 0, 0)), 0)
        with patch.object(Colors, 'CALIBRATION_FILE', self.palette), \
             patch.object(Colors, 'PALETTE_FILE', old_palette), \
             patch.object(Colors.load_positions, '__defaults__', (positions,)):
            self.assertEqual(Colors.load_calibration(self.palette), {'anchor': None, 'count': len(values)})
            self.assertEqual([(color.x, color.y) for color in Colors.allColors], coordinates)
            self.assertEqual([list(color.RGB) for color in Colors.allColors], values)
            self.assertEqual(PixelData.closest_color((0, 0, 0)), 3)
            before = self.palette_state()
            positions.write_text(''.join(f'{x + 100}\n{y + 100}\n' for x, y in coordinates), encoding='utf-8')
            invalid = deepcopy(values)
            invalid[-1] = [1, 2, 999]
            old_palette.write_text(json.dumps(invalid), encoding='utf-8')
            with self.assertRaises(ValueError):
                Colors.load_calibration(self.palette)
            self.assertEqual(self.palette_state(), before)
            self.assertEqual(PixelData.closest_color((0, 0, 0)), 3)

            # The actual legacy positions -> palette -> calibration chain
            # must keep its full supported byte budget and rollback semantics.
            limit = 8 * 1024 * 1024
            raw = json.dumps(values).encode('utf-8')
            old_palette.write_bytes(raw + b' ' * (limit - len(raw)))
            self.assertEqual(Colors.load_calibration(self.palette),
                             {'anchor': None, 'count': len(values)})
            self.assertEqual([(color.x, color.y) for color in Colors.allColors],
                             [(x + 100, y + 100) for x, y in coordinates])
            self.assertEqual([list(color.RGB) for color in Colors.allColors], values)
            before = self.palette_state()
            positions.write_text(''.join(f'{x + 200}\n{y + 200}\n' for x, y in coordinates),
                                 encoding='utf-8')
            with old_palette.open('ab') as stream:
                stream.write(b' ' * 200)
            with self.observe_reads(old_palette) as reads:
                with self.assertRaises(ValueError):
                    Colors.load_calibration(self.palette)
            self.assertEqual(sum(actual for _requested, actual in reads), limit + 1)
            self.assertTrue(all(0 < requested <= 65536 for requested, _actual in reads))
            self.assertEqual(self.palette_state(), before)
            old_palette.write_text('[' * 2000 + '0' + ']' * 2000, encoding='utf-8')
            with self.assertRaises(ValueError):
                Colors.load_calibration(self.palette)
            self.assertEqual(self.palette_state(), before)
            self.assertEqual(PixelData.closest_color((0, 0, 0)), 3)

    def test_calibration_byte_budget_matches_existing_profile_context_budget(self):
        limit = 8 * 1024 * 1024
        self.assertEqual(ProfileStorage.MAX_CALIBRATION_CONTEXT_BYTES, limit)
        raw = json.dumps(self.payload()).encode('utf-8')
        self.palette.write_bytes(raw + b' ' * (limit - len(raw)))
        self.assertEqual(Colors.calibration_metadata(self.palette)['count'], 2)
        with self.palette.open('ab') as stream:
            stream.write(b' ' * 200)
        before = self.palette_state()
        with self.observe_reads(self.palette) as reads:
            with self.assertRaises(ValueError):
                Colors.load_calibration(self.palette)
        self.assertEqual(sum(actual for _requested, actual in reads), limit + 1)
        self.assertTrue(all(0 < requested <= 65536 for requested, _actual in reads))
        self.assertEqual(self.palette_state(), before)


class VerifiedColorReaderFlowTests(ColorStorageFixture):
    profile = 'microsoft-paint'
    context = 'current-calibration-fixture'
    workflow = 'Adaptive exact (recommended)'

    def seed(self):
        controls = {'OpenCustomColor': (10, 10), 'ConfirmColor': (20, 10),
                    'RedField': (30, 10), 'GreenField': (40, 10), 'BlueField': (50, 10)}
        ExactColorTools.save(self.profile, controls, anchor=make_anchor((0, 0, 600, 400)))
        entry = ColorCache.put_verified(self.profile, (17, 93, 208), (17, 93, 208),
            delta_e2000=0, method='numeric', confidence=98.5,
            context_fingerprint=self.context, workflow=self.workflow)
        return ColorCache.cache_path(self.profile), entry

    def load(self, profile=None, **kwargs):
        return ColorCache.load_cache(self.profile if profile is None else profile,
            context_fingerprint=kwargs.get('context_fingerprint', self.context),
            workflow=kwargs.get('workflow', self.workflow))

    def status(self):
        return CalibrationState.exact_color_state(self.profile, workflow=self.workflow,
                                                  context_fingerprint=self.context)

    def test_actual_cache_status_rejects_duplicate_keys_depth_items_and_nonfinite_data(self):
        path, entry = self.seed()
        raw = path.read_text(encoding='utf-8')
        cases = {
            'profile': raw.replace('"profile": "microsoft-paint"',
                '"profile": "different-profile", "profile": "microsoft-paint"', 1),
            'context': raw.replace('"context_fingerprint": ' + json.dumps(self.context),
                '"context_fingerprint": "old", "context_fingerprint": ' + json.dumps(self.context), 1),
            'verified': raw.replace('"verified": true', '"verified": false, "verified": true', 1),
            'nonfinite': raw.rstrip()[:-1] + ', "extra": NaN}',
            'depth': raw.rstrip()[:-1] + ', "extra": ' + '[' * 40 + '0' + ']' * 40 + '}',
            'items': raw.rstrip()[:-1] + ', "extra": [' + ','.join('0' for _ in range(100001)) + ']}',
        }
        for label, document in cases.items():
            with self.subTest(document=label):
                path.write_text(document, encoding='utf-8')
                before = path.read_bytes()
                cached = self.load()
                state = self.status()
                self.assertEqual(state, {'state': 'calibrated', 'available': True,
                    'verified': False, 'profile_key': self.profile})
                self.assertEqual(cached, {})
                self.assertEqual(path.read_bytes(), before)
        path.write_text(raw, encoding='utf-8')
        self.assertEqual(self.load(), {'115DD0': entry})
        self.assertTrue(self.status()['verified'])

    def test_valid_writer_return_bom_profile_workflow_and_detached_reader_values_remain_supported(self):
        path, entry = self.seed()
        self.assertEqual(self.load(), {'115DD0': entry})
        self.assertEqual(entry['requested_rgb'], [17, 93, 208])
        self.assertEqual(entry['created_rgb'], [17, 93, 208])
        self.assertEqual(entry['confidence'], 98.5)
        self.assertEqual(entry['method'], 'numeric')
        raw = path.read_bytes()
        path.write_bytes(b'\xef\xbb\xbf' + raw)
        self.assertEqual(self.load(), {'115DD0': entry})
        self.assertEqual(self.load(context_fingerprint='old'), {})
        self.assertEqual(self.load(workflow='Calibrated palette'), {})
        self.assertEqual(self.load('gartic-phone'), {})
        result = self.load()
        result['115DD0']['created_rgb'][0] = 0
        self.assertEqual(self.load(), {'115DD0': entry})
        self.assertEqual(path.read_bytes(), b'\xef\xbb\xbf' + raw)

    def test_one_mebibyte_cache_budget_and_actual_limit_plus_one_read_are_preserved(self):
        path, entry = self.seed()
        limit = 1024 * 1024
        self.assertEqual(ColorCache.MAX_CACHE_BYTES, limit)
        raw = path.read_bytes()
        path.write_bytes(raw + b' ' * (limit - len(raw)))
        self.assertEqual(self.load(), {'115DD0': entry})
        with path.open('ab') as stream:
            stream.write(b' ' * 200)
        with self.observe_reads(path) as reads:
            self.assertEqual(self.load(), {})
        self.assertEqual(sum(actual for _requested, actual in reads), limit + 1)
        self.assertTrue(all(0 < requested <= 65536 for requested, _actual in reads))

    def test_actual_verified_writer_relearns_from_ambiguous_cache_without_retaining_old_evidence(self):
        path, _entry = self.seed()
        raw = path.read_text(encoding='utf-8').replace('"verified": true',
            '"verified": false, "verified": true', 1)
        path.write_text(raw, encoding='utf-8')
        entry = ColorCache.put_verified(self.profile, (200, 20, 30), (200, 20, 30),
            delta_e2000=0, method='spectrum', confidence=100,
            context_fingerprint=self.context, workflow=self.workflow)
        self.assertEqual(self.load(), {'C8141E': entry})
        self.assertEqual(set(RuntimePaths.read_json(path)['colors']), {'C8141E'})


class PalettePublicationFlowTests(ColorStorageFixture):
    @staticmethod
    def sharing_error(code):
        error = PermissionError(errno.EACCES, 'temporary Windows sharing conflict')
        error.winerror = code
        return error

    def controller(self):
        app = GetColorPositions.CalibrationApp.__new__(GetColorPositions.CalibrationApp)
        app.closed = False
        app.job = None
        app.snapshot = None
        app.status = Value('ready')
        app.path = self.palette
        app.grid_path = self.root / 'calibration.grid.json'
        app.is_paint = True
        app.profile_key = 'microsoft-paint'
        app.anchor = make_anchor((-100, -50, 500, 350))
        app.pending = [(-90, -40), (-50, -30)]
        app.rgbs = [(255, 0, 0), (1, 2, 3)]
        app.map_names = ['Röd', 'Ink']
        app.map_indices = [0, 1]
        app.rows = Value(1)
        app.columns = Value(2)
        app.closed_events = []
        app.root = SimpleNamespace(destroy=lambda: app.closed_events.append('destroy'))
        app.on_close = lambda: app.closed_events.append('on_close')
        return app

    def test_actual_controller_retries_transient_sharing_then_closes_only_after_complete_save(self):
        replace = os.replace
        for code in (5, 32, 33):
            with self.subTest(winerror=code):
                app = self.controller()
                previous = self.write_payload(self.payload('microsoft-paint'))
                attempts = []

                def publish(source, destination):
                    if Path(destination) == self.palette:
                        attempts.append((Path(source), Path(destination)))
                        self.assertEqual(app.closed_events, [])
                        if len(attempts) == 1:
                            self.assertEqual(self.palette.read_bytes(), previous)
                            raise self.sharing_error(code)
                    return replace(source, destination)

                with patch.object(RuntimePaths.sys, 'platform', 'win32'), \
                     patch.object(RuntimePaths.os, 'replace', side_effect=publish), \
                     patch.object(RuntimePaths.time, 'sleep') as delay:
                    self.assertIsNone(app.save())
                self.assertTrue(app.closed)
                self.assertEqual(app.closed_events, ['destroy', 'on_close'])
                self.assertEqual(len(attempts), 2)
                self.assertEqual(attempts[0], attempts[1])
                delay.assert_called_once_with(.01)
                saved = RuntimePaths.read_json(self.palette)
                self.assertEqual(saved['profile'], 'microsoft-paint')
                self.assertEqual(saved['anchor'], app.anchor)
                self.assertEqual(saved['state'], 'calibrated')
                self.assertEqual(saved['verification'], {'method': 'manual-palette-capture',
                    'source': 'user-reviewed-capture'})
                self.assertEqual(saved['colors'], [
                    {'name': name, 'position': list(point), 'rgb': list(rgb), 'game_index': index}
                    for index, (name, point, rgb) in enumerate(zip(app.map_names, app.pending, app.rgbs))])
                self.assertEqual(RuntimePaths.read_json(app.grid_path), {'rows': 1, 'columns': 2})
                self.assertFalse(any(path.suffix == '.tmp' for path in self.root.iterdir()))

    def test_actual_controller_keeps_reviewed_draft_and_file_after_permanent_failure(self):
        app = self.controller()
        previous = self.write_payload(self.payload('microsoft-paint'))
        draft = deepcopy((app.pending, app.rgbs, app.map_names, app.map_indices, app.anchor))
        with patch.object(RuntimePaths.sys, 'platform', 'win32'), \
             patch.object(RuntimePaths.os, 'replace', side_effect=self.sharing_error(32)) as replace, \
             patch.object(RuntimePaths.time, 'sleep') as delay:
            self.assertIsNone(app.save())
        self.assertFalse(app.closed)
        self.assertEqual(app.closed_events, [])
        self.assertIn('Could not save', app.status.get())
        self.assertEqual(self.palette.read_bytes(), previous)
        self.assertEqual((app.pending, app.rgbs, app.map_names, app.map_indices, app.anchor), draft)
        self.assertFalse(app.grid_path.exists())
        self.assertEqual(replace.call_count, 10)
        self.assertAlmostEqual(sum(call.args[0] for call in delay.call_args_list), .65)
        self.assertEqual(list(self.root.iterdir()), [self.palette])

    def test_primary_storage_error_is_preserved_when_owned_temporary_cleanup_also_fails(self):
        previous = self.write_payload(self.payload())
        failure = OSError(errno.EIO, 'primary durable write failure')
        cleanup = PermissionError(errno.EACCES, 'temporary cleanup also denied')
        unlink = Path.unlink
        leftovers = []

        def deny_owned(path, *args, **kwargs):
            if path.parent == self.root and path != self.palette:
                leftovers.append(path)
                raise cleanup
            return unlink(path, *args, **kwargs)

        try:
            with patch.object(RuntimePaths.os, 'fsync', side_effect=failure), \
                 patch.object(Path, 'unlink', new=deny_owned):
                with self.assertRaises(OSError) as caught:
                    Colors.save_calibration([(20, 20)], [(1, 2, 3)], self.palette)
            self.assertIs(caught.exception, failure)
            self.assertEqual(self.palette.read_bytes(), previous)
            self.assertTrue(leftovers)
        finally:
            for path in set(leftovers):
                unlink(path, missing_ok=True)

    def test_shared_unsupported_fsync_fallback_keeps_actual_controller_save_usable(self):
        app = self.controller()
        self.write_payload(self.payload('microsoft-paint'))
        with patch.object(RuntimePaths.os, 'fsync', side_effect=OSError(errno.ENOTSUP, 'unsupported fsync')):
            self.assertIsNone(app.save())
        self.assertTrue(app.closed)
        self.assertEqual(Colors.calibration_metadata(self.palette)['count'], 2)
        self.assertEqual(app.closed_events, ['destroy', 'on_close'])

    def test_save_preserves_metadata_returns_none_and_never_publishes_nonfinite_verification(self):
        data = self.payload()
        before = self.palette_state()
        self.assertIsNone(Colors.save_calibration([row['position'] for row in data['colors']],
            [row.get('rgb', row.get('argb')) for row in data['colors']], self.palette,
            names=[row['name'] for row in data['colors']], indices=[0, 1],
            anchor=data['anchor'], profile_key='generic', state='verified', verification=data['verification']))
        self.assertEqual(self.palette_state(), before)
        saved = RuntimePaths.read_json(self.palette)
        self.assertEqual(saved['verification'], data['verification'])
        self.assertEqual(saved['anchor'], data['anchor'])
        self.assertEqual(saved['colors'][0], {'name': 'Röd', 'position': [-90, -40],
            'rgb': [255, 127, 127], 'game_index': 0})
        previous = self.palette.read_bytes()
        with self.assertRaises(ValueError):
            Colors.save_calibration([(20, 20)], [(1, 2, 3)], self.palette,
                verification={'confidence': float('nan')})
        self.assertEqual(self.palette.read_bytes(), previous)
        self.assertEqual(self.palette_state(), before)
        self.assertEqual(list(self.root.iterdir()), [self.palette])


if __name__ == '__main__':
    unittest.main()
