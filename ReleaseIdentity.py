"""Bind a release tag to the exact build commit before assets are published.

Verification is read-only by default. The release workflow may explicitly
create a missing tag; an existing ref is never updated or deleted. GitHub CLI
uses its normal Actions token, and no release asset is downloaded here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
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


def verify_draft_assets(tag, expected_commit, paths, *, run=subprocess.run):
    """Compare GitHub's draft metadata to the four files provided to release upload."""
    from ReleasePackage import sha256
    tag, expected_commit = _validate_inputs(tag, expected_commit)
    paths = tuple(map(Path, paths))
    expected = {path.name: path for path in paths}
    if len(paths) != 4 or len(expected) != 4:
        raise ReleaseIdentityError('Publication requires four distinct local release files.')
    try:
        result = run(['gh', 'release', 'view', tag, '--repo', 'github.com/' + REPOSITORY,
                      '--json', 'tagName,targetCommitish,isDraft,assets'],
                     capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
        if result.returncode or len(result.stdout) > 1024 * 1024:
            raise ReleaseIdentityError('Could not read a bounded draft release inventory.')
        release = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError, RecursionError) as error:
        raise ReleaseIdentityError('Could not read valid GitHub draft metadata.') from error
    if (not isinstance(release, dict) or release.get('isDraft') is not True
            or release.get('tagName') != tag or release.get('targetCommitish') != expected_commit):
        raise ReleaseIdentityError('The draft no longer matches the release tag and build commit.')
    assets = release.get('assets')
    if not isinstance(assets, list) or len(assets) != len(expected):
        raise ReleaseIdentityError('The draft must contain exactly the four verified release assets.')
    for asset in assets:
        name = asset.get('name') if isinstance(asset, dict) else None
        path = expected.pop(name, None) if isinstance(name, str) else None
        if path is None or asset.get('state') != 'uploaded':
            raise ReleaseIdentityError('The draft contains an unexpected, duplicate or incomplete asset.')
        try:
            size = path.stat().st_size
            if (type(asset.get('size')) is not int or size <= 0 or asset['size'] != size
                    or asset.get('digest') != 'sha256:' + sha256(path)):
                raise ReleaseIdentityError(f'The uploaded size or SHA-256 differs for {name}.')
        except OSError as error:
            raise ReleaseIdentityError(f'Cannot verify the local bytes for {name}.') from error
    return {'verified_draft_assets': len(assets)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--expected-commit', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--create-missing-tag', action='store_true', help='Explicitly create a missing ref at the build commit; never change an existing ref.')
    mode.add_argument('--verify-draft-assets', nargs=4, type=Path, metavar='FILE',
                      help='Require the GitHub draft to contain exactly these uploaded files with matching SHA-256.')
    args = parser.parse_args(argv)
    try:
        result = ensure_release_tag(args.tag, args.expected_commit, create_missing=args.create_missing_tag)
        if args.verify_draft_assets:
            result.update(verify_draft_assets(args.tag, args.expected_commit, args.verify_draft_assets))
    except ReleaseIdentityError as error:
        parser.exit(1, f'Release identity check failed: {error}\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
