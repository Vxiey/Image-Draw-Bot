"""Run narrow regressions against the exact pre-batch42 function bodies.

This writes evidence; it does not edit either checkout or execute the full
historical application. Use only after the parent grants a test window.
"""
import ast
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import DrawBot
import DrawTimeEstimate
import MobilePreview
import RealSpeedBudget

BASELINE = 'b75ef8e'
baseline_hashes = {}


def historical(module, name, owner=None):
    filename = module.__name__ + '.py'
    text = subprocess.check_output(['git', 'show', f'{BASELINE}:{filename}'], cwd=ROOT, text=True)
    baseline_hashes[filename] = hashlib.sha256(text.encode()).hexdigest()
    tree = ast.parse(text)
    if owner:
        tree = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 f'{BASELINE}:{filename}', 'exec'), namespace)
    return namespace[name], node


def historical_drop_install():
    # The original production registration block was inline in __init__. Keep
    # that exact AST body and only supply its original local root binding.
    _constructor, node = historical(DrawBot, '__init__', 'DrawBotApp')
    block = next(child for child in node.body if isinstance(child, ast.If)
                 and isinstance(child.test, ast.Call)
                 and isinstance(child.test.func, ast.Name) and child.test.func.id == 'hasattr'
                 and len(child.test.args) == 2
                 and isinstance(child.test.args[1], ast.Constant)
                 and child.test.args[1].value == 'drop_target_register')
    wrapper = ast.parse('def install(self):\n    root = self.root\n').body[0]
    wrapper.body.append(block)
    namespace = dict(vars(DrawBot))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                 f'{BASELINE}:DrawBot.py:inline-drop-registration', 'exec'), namespace)
    return namespace['install']


def main():
    prefix = 'test_v148_application_batch42_'
    groups = [
        ('A4201', prefix + 'mobile_encoder.MobileEncoderTests.test_public_queue_keeps_one_detached_snapshot_and_no_inner_rgba_conversion',
         MobilePreview, '_image_png_bytes', historical(MobilePreview, '_image_png_bytes')[0]),
        ('A4202', prefix + 'capture_preview.CapturePreviewTests.test_real_dialog_matches_thumbnail_pixels_without_full_capture_copy',
         DrawBot.DrawBotApp, 'display_screen', historical(DrawBot, 'display_screen', 'DrawBotApp')[0]),
        ('A4203', prefix + 'preview_drop.PreviewDropTests.test_all_twelve_registered_pages_keep_the_verified_browser_drop_gesture',
         DrawBot.DrawBotApp, '_install_image_drop_targets', historical_drop_install()),
        ('A4204', prefix + 'startup_defaults.StartupProfileDefaultsTests.test_missing_file_starts_with_the_profile_defaults_before_ui_and_options',
         DrawBot.DrawBotApp, '__init__', historical(DrawBot, '__init__', 'DrawBotApp')[0]),
        ('N4101-policy-completion', prefix + 'delivery_speed.DeliverySpeedTests.test_public_budget_and_visible_eta_use_only_matching_resolved_options',
         RealSpeedBudget, 'apply_budget_policy', historical(RealSpeedBudget, 'apply_budget_policy')[0]),
        ('N4101-eta-completion', prefix + 'delivery_speed.DeliverySpeedTests.test_public_budget_and_visible_eta_use_only_matching_resolved_options',
         DrawTimeEstimate, '_measured_throughput_floor', historical(DrawTimeEstimate, '_measured_throughput_floor')[0]),
        ('N4101-producer-completion', prefix + 'delivery_speed.DeliverySpeedTests.test_actual_completed_executor_records_its_final_delivery_context',
         DrawBot, 'execute_plan', historical(DrawBot, 'execute_plan')[0]),
    ]
    names = set(baseline_hashes) | {name.split('.')[0] + '.py' for _, name, *_rest in groups}
    before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names)}
    rows = []
    for group, method, target, attribute, function in groups:
        stream = io.StringIO()
        with patch.object(target, attribute, new=function):
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromName(method))
        rows.append({'group': group, 'method': method, 'tests_run': result.testsRun,
            'reproduced': bool(result.failures) and not result.errors and not result.skipped,
            'failures': [{'test': test.id(), 'traceback': trace.replace(str(ROOT), '$FINAL')}
                         for test, trace in result.failures],
            'errors': [{'test': test.id(), 'traceback': trace.replace(str(ROOT), '$FINAL')}
                       for test, trace in result.errors],
            'raw_log': stream.getvalue().replace(str(ROOT), '$FINAL')})
        print(json.dumps({'group': group, 'reproduced': rows[-1]['reproduced'],
                          'failures': len(result.failures), 'errors': len(result.errors)}), flush=True)
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names)}
    report = {'schema': 1, 'local_baseline_commit': BASELINE,
        'equivalent_public_commit': 'e33fa67d17e3c33ccda8e736e7e16c2582d9fc06',
        'equivalent_public_tree': '72e55f2a6d3dad971a13e9ab9141aa521cf15177',
        'method': 'Exact historical function bodies from Git, each substituted independently into the current complete public-call regression. No source file is changed.',
        'count_boundary': 'Four new groups. The three separate N4101 caller checks are one existing-contract completion and add zero IDs. Subtest assertion counts are not fix counts.',
        'baseline_source_sha256': baseline_hashes,
        'source_test_hashes_before': before, 'source_test_hashes_after': after,
        'changed_sources': sorted(name for name in before if before[name] != after[name]),
        'all_reproduced': all(row['reproduced'] for row in rows), 'checks': rows}
    (ROOT / 'docs' / 'v148-batch42-application-historical.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
