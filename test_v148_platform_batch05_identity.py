import copy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ReleaseIdentity as identity

TAG = 'v1.0.148'
COMMIT = '1' * 40
OTHER = '2' * 40
BASE = 'repos/' + identity.REPOSITORY
REF_ENDPOINT = BASE + '/git/ref/tags/' + TAG


def ref(sha=COMMIT, kind='commit'):
    return {'ref': 'refs/tags/' + TAG, 'object': {'type': kind, 'sha': sha}}


class MemoryApi:
    def __init__(self, current=None):
        self.current = current
        self.objects = {}
        self.calls = []
        self.create_error = None
        self.racing_ref = None

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, copy.deepcopy(payload)))
        if method == 'GET':
            if endpoint == REF_ENDPOINT:
                if self.current is None:
                    raise identity.ApiError(method, endpoint, 404)
                return copy.deepcopy(self.current)
            return copy.deepcopy(self.objects[endpoint])
        if method != 'POST' or endpoint != BASE + '/git/refs':
            raise AssertionError('No existing ref may be mutated')
        if self.create_error is not None:
            self.current = self.racing_ref
            raise identity.ApiError(method, endpoint, self.create_error)
        self.current = ref(payload['sha'])
        return copy.deepcopy(self.current)


class ReleaseTagIdentityTests(unittest.TestCase):
    def test_matching_lightweight_and_nested_annotated_tags_are_read_only(self):
        for annotated in (False, True):
            api = MemoryApi(ref('a' * 40, 'tag') if annotated else ref())
            api.objects = {
                BASE + '/git/tags/' + 'a' * 40: {'sha': 'a' * 40, 'object': {'type': 'tag', 'sha': 'b' * 40}},
                BASE + '/git/tags/' + 'b' * 40: {'sha': 'b' * 40, 'object': {'type': 'commit', 'sha': COMMIT}},
            }
            with self.subTest(annotated=annotated):
                result = identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing=True)
                self.assertEqual(result['commit'], COMMIT)
                self.assertFalse(result['created'])
                self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_wrong_existing_tag_stops_before_creation_or_ref_mutation(self):
        api = MemoryApi(ref(OTHER))
        with self.assertRaisesRegex(identity.ReleaseIdentityError, 'not build commit'):
            identity.ensure_release_tag(TAG, COMMIT, create_missing=True, api=api)
        self.assertEqual(api.calls, [('GET', REF_ENDPOINT, None)])
        self.assertEqual(api.current, ref(OTHER))

    def test_default_check_does_not_create_a_missing_ref(self):
        api = MemoryApi()
        with self.assertRaisesRegex(identity.ReleaseIdentityError, 'does not exist'):
            identity.ensure_release_tag(TAG, COMMIT, api=api)
        self.assertEqual(api.calls, [('GET', REF_ENDPOINT, None)])

    def test_explicit_missing_tag_creation_is_exact_and_reread(self):
        api = MemoryApi()
        result = identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing=True)
        self.assertTrue(result['created'])
        self.assertEqual(api.calls, [
            ('GET', REF_ENDPOINT, None),
            ('POST', BASE + '/git/refs', {'ref': 'refs/tags/' + TAG, 'sha': COMMIT}),
            ('GET', REF_ENDPOINT, None),
        ])

    def test_creation_race_accepts_only_the_same_commit_without_overwriting(self):
        for status in (409, 422):
            for racing_ref in (ref(), ref(OTHER), None):
                api = MemoryApi()
                api.create_error, api.racing_ref = status, racing_ref
                with self.subTest(status=status, racing_ref=racing_ref):
                    if racing_ref == ref():
                        result = identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing=True)
                        self.assertFalse(result['created'])
                    else:
                        with self.assertRaises(identity.ReleaseIdentityError):
                            identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing=True)
                self.assertEqual([method for method, _, _ in api.calls], ['GET', 'POST', 'GET'])
                self.assertEqual(api.current, racing_ref)

    def test_permission_failure_is_not_treated_as_a_missing_tag(self):
        for status in (401, 403, 429, 500):
            api = MemoryApi()
            with patch.object(api, 'request', side_effect=identity.ApiError('GET', REF_ENDPOINT, status)) as request:
                with self.subTest(status=status), self.assertRaises(identity.ApiError):
                    identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing=True)
                request.assert_called_once_with('GET', REF_ENDPOINT)

    def test_malformed_different_or_cyclic_tag_objects_fail_without_mutation(self):
        bad_rows = [[], {}, {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': COMMIT}},
                    ref(COMMIT, 'blob'), ref('partial'), ref('a' * 40, 'tag')]
        for row in bad_rows:
            api = MemoryApi(row)
            api.objects[BASE + '/git/tags/' + 'a' * 40] = {
                'sha': 'a' * 40, 'object': {'type': 'tag', 'sha': 'a' * 40}}
            with self.subTest(row=row), self.assertRaises(identity.ReleaseIdentityError):
                identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing=True)
            self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_invalid_inputs_fail_before_a_metadata_request(self):
        for tag, commit in (('../main', COMMIT), ('v1.0.148\n', COMMIT), (TAG, 'HEAD'), (TAG, True)):
            api = MemoryApi()
            with self.subTest(tag=tag, commit=commit), self.assertRaises(identity.ReleaseIdentityError):
                identity.ensure_release_tag(tag, commit, api=api, create_missing=True)
            self.assertEqual(api.calls, [])
        api = MemoryApi()
        with self.assertRaises(identity.ReleaseIdentityError):
            identity.ensure_release_tag(TAG, COMMIT, api=api, create_missing='false')
        self.assertEqual(api.calls, [])


class GhApiBoundaryTests(unittest.TestCase):
    def test_creation_uses_structured_stdin_without_a_command_shell(self):
        payload = {'ref': 'refs/tags/' + TAG, 'sha': COMMIT}
        response = SimpleNamespace(returncode=0, stdout='HTTP/2.0 201 Created\r\nContent-Type: application/json\r\n\r\n' + json.dumps(ref()))
        with patch.object(identity.subprocess, 'run', return_value=response) as run:
            self.assertEqual(identity.GhApi().request('POST', BASE + '/git/refs', payload), ref())
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertEqual(json.loads(run.call_args.kwargs['input']), payload)
        self.assertEqual(run.call_args.args[0][-2:], ['--input', '-'])

    def test_missing_http_status_or_invalid_body_cannot_become_a_successful_check(self):
        for raw in (json.dumps(ref()), 'HTTP/2 200 OK\n\nnot JSON', 'HTTP/2 200 OK\nmissing separator'):
            with self.subTest(raw=raw), patch.object(identity.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=raw)):
                with self.assertRaises(identity.ReleaseIdentityError):
                    identity.GhApi().request('GET', REF_ENDPOINT)

    def test_transport_failure_is_bounded_and_does_not_echo_private_output(self):
        failure = subprocess.TimeoutExpired(['gh', 'api'], 60, output='SENSITIVE OUTPUT', stderr='SECRET TOKEN')
        with patch.object(identity.subprocess, 'run', side_effect=failure):
            with self.assertRaises(identity.ReleaseIdentityError) as caught:
                identity.GhApi().request('GET', REF_ENDPOINT)
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertNotIn('SENSITIVE', str(caught.exception))


class ReleaseWorkflowPublicationTests(unittest.TestCase):
    def workflow(self):
        return Path(__file__).with_name('.github').joinpath('workflows/build-windows.yml').read_text(encoding='utf-8')

    def test_tag_verification_brackets_upload_and_creation_uses_verified_existing_ref(self):
        text = self.workflow()
        first = text.index('python ReleaseIdentity.py --tag $tag --expected-commit $env:GITHUB_SHA --create-missing-tag')
        create = text.index('gh release create $tag --verify-tag')
        upload = text.index('gh release upload $tag')
        second = text.index('python ReleaseIdentity.py --tag $tag --expected-commit $env:GITHUB_SHA\n', upload)
        publish = text.index('gh release edit $tag --draft=false')
        self.assertLess(first, create)
        self.assertLess(create, upload)
        self.assertLess(upload, second)
        self.assertLess(second, publish)

    def test_main_and_tag_runs_cannot_interleave_different_builds_assets(self):
        # This is the concrete publication race: two valid builds of the same
        # commit can have different EXE bytes, so mixed assets break checksums.
        first, second = b'build A', b'build B'
        mixed = {'zip': second, 'setup': first,
                 'zip_hash': hashlib.sha256(second).hexdigest(),
                 'setup_hash': hashlib.sha256(second).hexdigest()}
        self.assertNotEqual(hashlib.sha256(mixed['setup']).hexdigest(), mixed['setup_hash'])
        block = self.workflow().split('\nconcurrency:\n', 1)[1].split('\njobs:', 1)[0]
        fields = dict(line.strip().split(':', 1) for line in block.splitlines()
                      if ':' in line and not line.lstrip().startswith('#'))
        group = fields['group'].strip()
        keys = {group.replace('${{ github.ref }}', ref) for ref in ('refs/heads/main', 'refs/tags/' + TAG)}
        self.assertEqual(len(keys), 1, 'main/tag publishers must hold the same workflow mutex')
        self.assertEqual(fields['cancel-in-progress'].strip(), 'false')
        self.assertEqual(fields['queue'].strip(), 'max', 'a third request must not replace the sole pending publication')


if __name__ == '__main__':
    unittest.main()
