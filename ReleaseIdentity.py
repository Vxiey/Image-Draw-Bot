"""Bind a release tag to the exact build commit before assets are published.

Verification is read-only by default. The release workflow may explicitly
create a missing tag; an existing ref is never updated or deleted. GitHub CLI
uses its normal Actions token, and no release asset is downloaded here.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from urllib.parse import quote

REPOSITORY = 'Vxiey/Image-Draw-Bot'
_BASE = f'repos/{REPOSITORY}'
_SHA = re.compile(r'[0-9a-fA-F]{40}')
_TAG = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-(?:rc[0-9]+|beta))?')
MAX_TAG_DEPTH = 16


class ReleaseIdentityError(RuntimeError):
    pass


class ApiError(ReleaseIdentityError):
    def __init__(self, method, endpoint, status):
        self.status = status
        super().__init__(f'GitHub {method} {endpoint} failed (HTTP {status}).')


class GhApi:
    def request(self, method, endpoint, payload=None):
        if (method not in {'GET', 'POST'} or not endpoint.startswith(_BASE + '/git/')
                or (method == 'POST' and endpoint != _BASE + '/git/refs')):
            raise ReleaseIdentityError('Only Git metadata reads and missing-tag creation are supported.')
        arguments = ['gh', 'api', '--hostname', 'github.com', '--method', method,
                     '--include', '-H', 'Accept: application/vnd.github+json', endpoint]
        if method == 'POST':
            if (not isinstance(payload, dict) or set(payload) != {'ref', 'sha'}
                    or not isinstance(payload['ref'], str) or not payload['ref'].startswith('refs/tags/')):
                raise ReleaseIdentityError('Only a complete release-tag ref may be created.')
            _validate_inputs(payload['ref'][len('refs/tags/'):], payload['sha'])
            arguments.extend(['--input', '-'])
        elif payload is not None:
            raise ReleaseIdentityError('Git metadata reads do not accept mutation data.')
        try:
            result = subprocess.run(arguments, input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, text=True, encoding='utf-8',
                                    timeout=60, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            # Do not echo a token-bearing environment, transport headers or CLI
            # stderr. A failed creation is not blindly retried.
            raise ReleaseIdentityError('Could not complete the release-tag metadata request.') from error
        header, separator, body = result.stdout.replace('\r\n', '\n').partition('\n\n')
        match = re.fullmatch(r'HTTP/\S+ (\d{3})(?: .*)?', header.split('\n', 1)[0])
        if not separator or match is None:
            raise ReleaseIdentityError('GitHub did not return a valid HTTP status for the release tag.')
        status = int(match.group(1))
        if result.returncode or status != (200 if method == 'GET' else 201):
            raise ApiError(method, endpoint, status)
        if len(body) > 1024 * 1024:
            raise ReleaseIdentityError('Release-tag metadata exceeds the supported response size.')
        try:
            return json.loads(body)
        except (ValueError, RecursionError) as error:
            raise ReleaseIdentityError('GitHub returned invalid release-tag JSON.') from error


def _sha(value):
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ReleaseIdentityError('A full 40-character Git commit/object SHA is required.')
    return value.lower()


def _validate_inputs(tag, expected_commit):
    if not isinstance(tag, str) or len(tag) > 128 or _TAG.fullmatch(tag) is None:
        raise ReleaseIdentityError('A supported versioned release tag is required.')
    return tag, _sha(expected_commit)


def _object(row):
    if not isinstance(row, dict) or not isinstance(row.get('object'), dict):
        raise ReleaseIdentityError('GitHub returned an invalid Git object identity.')
    item = row['object']
    if item.get('type') not in {'commit', 'tag'}:
        raise ReleaseIdentityError('A release tag must resolve to a commit.')
    return item['type'], _sha(item.get('sha'))


def _read_tag(api, tag):
    endpoint = f'{_BASE}/git/ref/tags/{quote(tag, safe="")}'
    try:
        row = api.request('GET', endpoint)
    except ApiError as error:
        if error.status == 404:
            return None
        raise
    if not isinstance(row, dict) or row.get('ref') != 'refs/tags/' + tag:
        raise ReleaseIdentityError('GitHub returned a different release tag.')
    kind, sha = _object(row)
    seen = set()
    while kind == 'tag':
        if sha in seen or len(seen) >= MAX_TAG_DEPTH:
            raise ReleaseIdentityError('Annotated release tags contain a cycle or exceed the supported depth.')
        seen.add(sha)
        row = api.request('GET', f'{_BASE}/git/tags/{sha}')
        if not isinstance(row, dict) or _sha(row.get('sha')) != sha:
            raise ReleaseIdentityError('GitHub returned a different annotated-tag object.')
        kind, sha = _object(row)
    return sha


def ensure_release_tag(tag, expected_commit, *, create_missing=False, api=None):
    tag, expected_commit = _validate_inputs(tag, expected_commit)
    if type(create_missing) is not bool:
        raise ReleaseIdentityError('Missing-tag creation requires an explicit Boolean option.')
    api = GhApi() if api is None else api
    actual = _read_tag(api, tag)
    created = False
    if actual is None:
        if not create_missing:
            raise ReleaseIdentityError(f'Release tag {tag} does not exist.')
        try:
            api.request('POST', _BASE + '/git/refs', {'ref': 'refs/tags/' + tag, 'sha': expected_commit})
            created = True
        except ApiError as error:
            if error.status not in (409, 422):
                raise
            # Another authorized writer may have created the ref between our
            # read and create. Verify that exact ref; never force-update it.
            actual = _read_tag(api, tag)
            if actual is None:
                raise
        else:
            actual = _read_tag(api, tag)
            if actual is None:
                raise ReleaseIdentityError('The newly created release tag could not be verified.')
    if actual != expected_commit:
        raise ReleaseIdentityError(f'Release tag {tag} resolves to {actual}, not build commit {expected_commit}. Existing tags are never rewritten.')
    return {'repository': REPOSITORY, 'tag': tag, 'commit': actual, 'created': created}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--create-missing-tag', action='store_true', help='Explicitly create a missing ref at the build commit; never change an existing ref.')
    args = parser.parse_args(argv)
    try:
        result = ensure_release_tag(args.tag, args.expected_commit, create_missing=args.create_missing_tag)
    except ReleaseIdentityError as error:
        parser.exit(1, f'Release identity check failed: {error}\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
