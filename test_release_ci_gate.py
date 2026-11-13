import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import ReleaseCiGate as gate

SHA = 'a' * 40


def row(**updates):
    out = dict(id=12, head_sha=SHA, head_branch='main', event='push', status='completed',
               conclusion='success', repository={'full_name': gate.REPOSITORY})
    out.update(updates)
    return out


def runner(rows):
    return Mock(return_value=SimpleNamespace(returncode=0,
        stdout=json.dumps({'workflow_runs': rows})))


class ReleaseCiGateTests(unittest.TestCase):
    def test_success_is_exact_commit_read_only_and_bounded(self):
        run = runner([row()])
        result = gate.verify_ci(SHA.upper(), run=run)
        self.assertEqual(result, {'commit': SHA, 'run_id': 12, 'status': 'success'})
        args, kwargs = run.call_args
        self.assertIn('GET', args[0])
        self.assertIn('/actions/workflows/ci.yml/runs?head_sha=' + SHA, args[0][-1])
        self.assertEqual(kwargs['timeout'], 60)
        self.assertFalse(kwargs['shell'])

    def test_wrong_commit_repository_and_event_cannot_satisfy_gate(self):
        for updates in ({'head_sha': 'b'*40}, {'repository': {'full_name': 'other/repo'}},
                        {'event': 'workflow_dispatch'}, {'event': 'pull_request'}, {'head_branch': 'feature'}, {'head_branch': None}):
            with self.subTest(updates=updates), self.assertRaises(gate.ReleaseCiError):
                gate.verify_ci(SHA, run=runner([row(**updates)]))

    def test_latest_run_cannot_be_replaced_with_older_green_run(self):
        for status, conclusion in [('queued', None), ('in_progress', None),
                                   ('completed', 'failure'), ('completed', 'cancelled'),
                                   ('completed', 'skipped'), ('completed', None)]:
            with self.subTest(status=status, conclusion=conclusion), self.assertRaises(gate.ReleaseCiError):
                gate.verify_ci(SHA, run=runner([row(), row(id=13, status=status, conclusion=conclusion)]))

    def test_invalid_inputs_fail_before_network(self):
        for value in ('main', '', SHA+'?other=1', None):
            run = runner([])
            with self.subTest(value=value), self.assertRaises(gate.ReleaseCiError):
                gate.verify_ci(value, run=run)
            run.assert_not_called()

    def test_missing_malformed_and_transport_errors_fail_closed(self):
        for rows in ([], [None], [row(id=True)], [row(repository=None)]):
            with self.subTest(rows=rows), self.assertRaises(gate.ReleaseCiError):
                gate.verify_ci(SHA, run=runner(rows))
        for value in ('invalid', '[]', '{}', '{"workflow_runs": null}', ' '*2_000_001):
            with self.subTest(value=value[:30]), self.assertRaises(gate.ReleaseCiError):
                gate.verify_ci(SHA, run=Mock(return_value=SimpleNamespace(returncode=0, stdout=value)))
        with self.assertRaises(gate.ReleaseCiError):
            gate.verify_ci(SHA, run=Mock(return_value=SimpleNamespace(returncode=1, stdout='token-secret')))
        for error in (OSError('private'), subprocess.TimeoutExpired('gh', 60)):
            with self.assertRaises(gate.ReleaseCiError):
                gate.verify_ci(SHA, run=Mock(side_effect=error))

    def test_workflow_checks_ci_and_gui_before_mutating_release(self):
        text = Path(__file__).with_name('.github').joinpath('workflows/build-windows.yml').read_text()
        self.assertIn('actions: read', text)
        self.assertIn("'--smoke-test'", text)
        self.assertIn('timeout=90', text)
        self.assertLess(text.index("'--smoke-test'"), text.index('gh release create'))
        self.assertLess(text.index('python ReleaseCiGate.py --expected-commit $env:GITHUB_SHA'),
                        text.index('python ReleaseIdentity.py --tag $tag --expected-commit $env:GITHUB_SHA --create-missing-tag'))


if __name__ == '__main__':
    unittest.main()
