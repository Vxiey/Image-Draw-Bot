"""Actual native/controller boundary regressions, including historical negatives."""
from contextlib import ExitStack
import hashlib
import importlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import types
import unittest
from unittest.mock import patch


BASELINE = 'e33fa67d17e3c33ccda8e736e7e16c2582d9fc06'
MODULES = ('WindowsMouse', 'DpiSupport', 'ScreenGuard', 'StrokeDeliveryVerification', 'ScreenRecording')
TESTS = ('test_v148_native_batch42_modifiers', 'test_v148_native_batch42_delivery_coverage',
         'test_v148_native_batch42_dpi_identity', 'test_v148_native_batch42_recording_compare')


def run_suite(names):
    stream = io.StringIO()
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromNames(names))
    return {'tests': result.testsRun, 'failures': len(result.failures),
            'errors': len(result.errors), 'skips': len(result.skipped),
            'seconds': time.perf_counter() - started, 'successful': result.wasSuccessful(),
            'raw_log': stream.getvalue().replace(str(Path.cwd()), '$REPO')}


def main():
    current = {name: importlib.import_module(name) for name in MODULES}
    tests = {name: importlib.import_module(name) for name in TESTS}
    historical = {}
    source_hashes = {}
    for name in MODULES:
        raw = subprocess.check_output(['git', 'show', BASELINE + ':' + name + '.py'])
        module = types.ModuleType('_batch42_before_' + name)
        sys.modules[module.__name__] = module
        exec(compile(raw, 'historical-' + name + '.py', 'exec'), module.__dict__)
        historical[name] = module
        source_hashes[name + '.py'] = {
            'historical': hashlib.sha256(raw).hexdigest(),
            'current': hashlib.sha256(Path(name + '.py').read_bytes()).hexdigest()}

    selectors = [
        TESTS[0] + '.ModifierOwnershipTests.test_each_modifier_blocks_arm_and_press_without_releasing_user_keys',
        TESTS[1] + '.BrowserCoverageTests.test_one_matching_site_does_not_confirm_the_rest_of_a_browser_stroke',
        TESTS[2] + '.DpiObservationTests.test_overlapping_window_monitor_reads_keep_complete_native_geometry',
        TESTS[3] + '.RecordingComparisonTests.test_actual_recording_size_never_exports_a_full_frame_and_stops_at_first_difference',
    ]
    before = {}
    for index, selector in enumerate(selectors):
        with ExitStack() as stack:
            if index == 0:
                stack.enter_context(patch.object(tests[TESTS[0]], 'WindowsMouse', historical['WindowsMouse'].WindowsMouse))
            elif index == 1:
                stack.enter_context(patch.object(tests[TESTS[1]], 'GuardedMouse', historical['ScreenGuard'].GuardedMouse))
                stack.enter_context(patch.object(tests[TESTS[1]], 'inspect_delivery', historical['StrokeDeliveryVerification'].inspect_delivery))
            elif index == 2:
                stack.enter_context(patch.object(current['ScreenGuard'], 'get_window_dpi_info', historical['DpiSupport'].get_window_dpi_info))
            else:
                stack.enter_context(patch.object(tests[TESTS[3]], 'append_recorded_frame', historical['ScreenRecording'].append_recorded_frame))
            before[selector] = run_suite([selector])
    after = run_suite(TESTS)
    unchanged = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == values['current']
                    for path, values in source_hashes.items())
    evidence = {'baseline_commit': BASELINE, 'python': platform.python_version(),
                'scope': 'Actual public code at native producer boundaries; no Windows desktop or physical input is available. Existing committed raster only.',
                'source_hashes': source_hashes, 'unchanged': unchanged,
                'historical_negatives': before, 'current_focused': after}
    Path('docs/v148-batch42-native-validation.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'historical': {name: {key: row[key] for key in ('tests', 'failures', 'errors', 'skips')}
                                     for name, row in before.items()},
                      'current': {key: after[key] for key in ('tests', 'failures', 'errors', 'skips', 'successful')},
                      'unchanged': unchanged}, indent=2))
    if not after['successful'] or not unchanged or any(row['successful'] for row in before.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
