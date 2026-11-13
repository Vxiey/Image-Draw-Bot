"""Candidate builds remain possible; incomplete/malformed scope cannot publish."""
import json
from pathlib import Path
import tempfile
import unittest

from ReleaseCandidateHardening import ReleaseGateError, validate_release_scope


def complete():
    return {'version': '1.0.148', 'target': 900, 'implemented': 900,
            'improvements': [{'id': i, 'description': 'Independent behavior',
                              'ledger': 'evidence.md'} for i in range(1, 901)]}


class ReleaseScopeGateTests(unittest.TestCase):
    def validate(self, data):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'docs').mkdir()
            (root/'docs/v148-improvements.json').write_text(json.dumps(data))
            return validate_release_scope(root)

    def test_complete_registry_can_pass_without_claiming_actual_work_is_complete(self):
        self.assertEqual(self.validate(complete()), {'version': '1.0.148',
            'target': 900, 'implemented': 900, 'passed': True})

    def test_missing_groups_false_count_duplicates_and_reduced_target_fail(self):
        for kind in ('missing', 'false-count', 'duplicate', 'reduced-target',
                     'bool-count', 'wrong-version', 'missing-evidence', 'bool-id'):
            data = complete()
            if kind == 'missing':
                data['improvements'] = data['improvements'][:886]; data['implemented'] = 886
            elif kind == 'false-count': data['implemented'] = 899
            elif kind == 'duplicate': data['improvements'][-1]['id'] = 1
            elif kind == 'reduced-target': data['target'] = 886
            elif kind == 'bool-count': data['implemented'] = True
            elif kind == 'wrong-version': data['version'] = '1.0.149'
            elif kind == 'missing-evidence': data['improvements'][0]['ledger'] = ''
            elif kind == 'bool-id': data['improvements'][0]['id'] = True
            with self.subTest(kind=kind), self.assertRaises(ReleaseGateError):
                self.validate(data)

    def test_malformed_missing_and_oversized_registry_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'docs').mkdir()
            path = root/'docs/v148-improvements.json'
            with self.assertRaises(ReleaseGateError): validate_release_scope(root)
            for payload in ('broken', '[]', '{}', ' '* (4*1024*1024+1)):
                path.write_text(payload)
                with self.subTest(size=len(payload)), self.assertRaises(ReleaseGateError):
                    validate_release_scope(root)

    def test_workflow_requires_scope_before_ci_tag_and_publication(self):
        text = Path(__file__).with_name('.github').joinpath('workflows/build-windows.yml').read_text()
        scope = text.index('python ReleaseCandidateHardening.py --scope-gate')
        self.assertLess(scope, text.index('python ReleaseCiGate.py'))
        self.assertLess(scope, text.index('--create-missing-tag'))
        self.assertLess(scope, text.index('gh release create'))


if __name__ == '__main__':
    unittest.main()
