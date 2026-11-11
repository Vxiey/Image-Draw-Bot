"""Malformed portable profiles cannot silently replace a working profile.

The real JSON reader, schema migration, validators, registry and atomic profile
publisher operate on temporary files. Only native dialog boundaries and the
application's settings/reload interface are supplied by the fixture.
"""
from contextlib import contextmanager, ExitStack
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import GameProfiles as profiles
import ProfilePortability as portability
import ProfileStorage as storage
from RuntimePaths import atomic_write_text


LEGACY_SECTIONS = ('renderer_settings', 'settings', 'resource_limits', 'calibration', 'canvas')


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ProfileValidationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        temporary = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = temporary / 'data'
        self.root.mkdir()
        self.incoming = temporary / 'incoming.drawprofile'
        builtins = {name: value for name, value in profiles.PROFILES.items()
                    if not value[0].startswith('custom-')}
        self.stack.enter_context(patch.dict(profiles.PROFILES, builtins, clear=True))
        self.stack.enter_context(patch.dict(profiles.PROFILE_UI))
        self.stack.enter_context(patch.object(portability, 'data_dir', lambda: self.root))
        self.stack.enter_context(patch.object(storage, 'data_dir', lambda: self.root))
        self.registry = self.root / 'profiles.json'
        self.name = 'Existing validation brushes'
        profiles.add_custom_profile(self.name, self.registry)
        self.key = profiles.PROFILES[self.name][0]
        self.paths = portability.portable_path_map(self.key)
        self.palette = {
            'version': 4, 'profile': self.key, 'state': 'calibrated',
            'colors': [{'name': 'Black', 'position': [10, 20], 'rgb': [0, 0, 0]}],
        }
        self.current_path = storage.profile_settings_file('generic')
        self.current_text = json.dumps({'settings_schema': 2, 'quality': 'Balanced'})
        atomic_write_text(self.current_path, self.current_text)
        self.seed_target()

    def seed_target(self):
        package = portability.build_package(self.name, {'quality': 'High detail', 'brush_px': '7'},
                                            {'palette': self.palette})
        portability.apply_package_to_paths(package, self.key)

    def app(self):
        app = SimpleNamespace(activity=None, closing=False, root=None,
                              game=Value('Other drawing app'), status=Value(''),
                              save_calls=0, reloads=[])

        def save_settings():
            app.save_calls += 1
            atomic_write_text(self.current_path, self.current_text)
            return True

        def reload_settings(name):
            app.reloads.append(name)
            key = profiles.PROFILES[name][0]
            app.loaded_settings = json.loads(storage.profile_settings_file(key).read_text(encoding='utf-8'))

        app.save_settings = save_settings
        app._apply_profile_change = reload_settings
        return app

    def legacy(self, **changes):
        return dict({'name': self.name, 'profile_key': self.key, 'schema_version': 0}, **changes)

    def write_incoming(self, document):
        self.incoming.write_text(json.dumps(document), encoding='utf-8')

    def state(self):
        return ({path.name: path.read_bytes() for path in self.root.iterdir()},
                dict(profiles.PROFILES), dict(profiles.PROFILE_UI))

    def attempt_replace(self, app):
        try:
            package = portability.read_profile_file(self.incoming)
            portability.import_package_into_app(app, package, action='replace')
        except Exception as error:
            return error
        return None

    def assert_rejected_without_publication(self):
        app = self.app()
        before = self.state()
        failure = self.attempt_replace(app)
        # Check real files first: on the historical source malformed schema 0
        # reached Replace and deleted the previously usable palette file.
        self.assertEqual(self.state(), before)
        self.assertIsInstance(failure, portability.ProfilePortabilityError)
        self.assertEqual(app.save_calls, 0)
        self.assertEqual(app.reloads, [])
        self.assertEqual(app.game.get(), 'Other drawing app')
        return failure

    @contextmanager
    def integer_budget(self):
        previous = sys.get_int_max_str_digits()
        limit = sys.int_info.str_digits_check_threshold
        try:
            sys.set_int_max_str_digits(limit)
            yield limit
        finally:
            sys.set_int_max_str_digits(previous)

    def numeric_document(self, digits):
        package = portability.build_package(self.name, {'quality': 'Balanced'}, {'palette': self.palette})
        package['created_by']['numeric_metadata'] = 'INTEGER_PLACEHOLDER'
        text = json.dumps(package)
        return text.replace('"INTEGER_PLACEHOLDER"', '7' * digits).encode('ascii')

    def test_falsey_legacy_sections_cannot_replace_existing_settings_or_calibration(self):
        for section in LEGACY_SECTIONS:
            for value in (False, 0, '', []):
                with self.subTest(section=section, value=value):
                    self.seed_target()
                    self.write_incoming(self.legacy(**{section: value}))
                    self.assert_rejected_without_publication()

    def test_malformed_legacy_section_cannot_hide_behind_a_valid_renderer_alias(self):
        for primary, alias in ((False, {'quality': 'Balanced'}),
                               ({'quality': 'Balanced'}, [])):
            with self.subTest(primary=primary, alias=alias):
                self.seed_target()
                self.write_incoming(self.legacy(renderer_settings=primary, settings=alias))
                self.assert_rejected_without_publication()

    def test_missing_null_and_empty_legacy_sections_keep_default_semantics(self):
        for label, sections in (
                ('missing', {}), ('null', dict.fromkeys(LEGACY_SECTIONS)),
                ('empty', {name: {} for name in LEGACY_SECTIONS})):
            with self.subTest(sections=label):
                self.seed_target()
                registry = self.registry.read_bytes()
                self.write_incoming(self.legacy(**sections))
                app = self.app()
                self.assertIsNone(self.attempt_replace(app))
                self.assertEqual(app.loaded_settings, {'settings_schema': 2})
                self.assertFalse(self.paths['palette'].exists())
                self.assertEqual(app.save_calls, 1)
                self.assertEqual(app.reloads, [self.name])
                self.assertEqual(self.registry.read_bytes(), registry)

    def test_valid_legacy_aliases_resources_canvas_and_palette_publish_to_the_right_owner(self):
        cases = (
            ({'renderer_settings': {'quality': 'High detail'}, 'settings': {'quality': 'Balanced'}},
             'High detail', 'replace'),
            ({'renderer_settings': {}, 'settings': {'quality': 'Balanced'}}, 'Balanced', 'replace'),
            ({'renderer_settings': None, 'settings': {'quality': 'Balanced'}}, 'Balanced', 'replace'),
            ({'settings': {'quality': 'Balanced'}}, 'Balanced', 'copy'),
        )
        for renderer, quality, action in cases:
            with self.subTest(renderer=renderer, action=action):
                self.seed_target()
                original = {path: path.read_bytes() for path in self.paths.values() if path.exists()}
                document = self.legacy(**renderer, resource_limits={'cpu_workers': '4'},
                                       canvas={'corners': [[1, 2], [101, 202]]}, palette=self.palette)
                self.write_incoming(document)
                package = portability.read_profile_file(self.incoming)
                app = self.app()
                name = portability.import_package_into_app(
                    app, package, action=action, copy_name='Imported validation brushes' if action == 'copy' else None)
                key = profiles.PROFILES[name][0]
                paths = portability.portable_path_map(key)
                self.assertEqual(app.loaded_settings['quality'], quality)
                self.assertEqual(app.loaded_settings['cpu_workers'], '4')
                self.assertEqual(app.loaded_settings['corners'], [[1, 2], [101, 202]])
                self.assertEqual(app.loaded_settings['settings_schema'], 2)
                palette = json.loads(paths['palette'].read_text(encoding='utf-8'))
                self.assertEqual(palette['profile'], key)
                self.assertEqual(palette['colors'], self.palette['colors'])
                self.assertEqual(json.loads(self.registry.read_text(encoding='utf-8'))[name], key)
                self.assertEqual(app.reloads, [name])
                if action == 'copy':
                    self.assertNotEqual(key, self.key)
                    self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_oversized_json_integer_is_a_profile_error_before_replace(self):
        previous = sys.get_int_max_str_digits()
        with self.integer_budget() as limit:
            self.incoming.write_bytes(self.numeric_document(limit + 1))
            failure = self.assert_rejected_without_publication()
            self.assertIsInstance(failure.__cause__, ValueError)
            self.assertNotIsInstance(failure.__cause__, portability.ProfilePortabilityError)
        self.assertEqual(sys.get_int_max_str_digits(), previous)

    def test_dialog_reports_integer_limit_without_mutation_or_unhandled_callback_error(self):
        app = self.app()
        before = self.state()
        escaped = None
        result = None
        previous = sys.get_int_max_str_digits()
        with self.integer_budget() as limit:
            self.incoming.write_bytes(self.numeric_document(limit + 1))
            with patch('tkinter.filedialog.askopenfilename', return_value=str(self.incoming)) as chooser, \
                    patch('tkinter.messagebox.showerror') as error, \
                    patch('tkinter.messagebox.showinfo') as info, \
                    patch('tkinter.messagebox.askyesnocancel') as collision:
                try:
                    result = portability.import_profile_dialog(app)
                except Exception as failure:
                    escaped = failure
        self.assertEqual(sys.get_int_max_str_digits(), previous)
        self.assertEqual(self.state(), before)
        self.assertIsNone(escaped, repr(escaped))
        self.assertIsNone(result)
        chooser.assert_called_once()
        error.assert_called_once()
        info.assert_not_called()
        collision.assert_not_called()
        self.assertEqual(app.save_calls, 0)
        self.assertEqual(app.reloads, [])

    def test_integer_at_active_digit_limit_remains_readable_and_importable(self):
        previous = sys.get_int_max_str_digits()
        with self.integer_budget() as limit:
            self.incoming.write_bytes(self.numeric_document(limit))
            package = portability.read_profile_file(self.incoming)
            self.assertEqual(str(package['created_by']['numeric_metadata']), '7' * limit)
            app = self.app()
            self.assertEqual(portability.import_package_into_app(app, package), self.name)
            self.assertEqual(app.loaded_settings['quality'], 'Balanced')
            self.assertEqual(app.reloads, [self.name])
        self.assertEqual(sys.get_int_max_str_digits(), previous)

    def test_existing_json_syntax_unicode_duplicate_and_depth_errors_remain_controlled(self):
        for raw, cause, message in (
                (b'{', json.JSONDecodeError, 'not valid UTF-8 JSON'),
                (b'\xff', UnicodeDecodeError, 'not valid UTF-8 JSON'),
                (b'{"same":1,"same":2}', None, 'duplicate JSON key'),
                (b'[' * 20 + b'0' + b']' * 20, None, 'deeply nested')):
            with self.subTest(raw=raw[:25]):
                self.incoming.write_bytes(raw)
                failure = self.assert_rejected_without_publication()
                self.assertIn(message, str(failure))
                if cause is None:
                    self.assertIsNone(failure.__cause__)
                else:
                    self.assertIsInstance(failure.__cause__, cause)


if __name__ == '__main__':
    unittest.main()
