"""Read-only, fail-closed verification of CI for the exact release commit."""
from __future__ import annotations

import argparse
import json
import re
import subprocess

from ReleaseIdentity import REPOSITORY


class ReleaseCiError(RuntimeError):
    pass


def verify_ci(commit, *, run=subprocess.run):
    if not isinstance(commit, str) or re.fullmatch(r'[0-9a-fA-F]{40}', commit) is None:
        raise ReleaseCiError('A full release commit SHA is required.')
    commit = commit.lower()
    endpoint = f'repos/{REPOSITORY}/actions/workflows/ci.yml/runs?head_sha={commit}&per_page=20'
    try:
        response = run(['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                        '-H', 'Accept: application/vnd.github+json', endpoint],
                       capture_output=True, text=True, encoding='utf-8',
                       timeout=60, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseCiError('Could not verify release CI; no publication is permitted.') from error
    if response.returncode or not isinstance(response.stdout, str) or len(response.stdout) > 2_000_000:
        raise ReleaseCiError('Could not read release CI metadata; no publication is permitted.')
    try:
        payload = json.loads(response.stdout)
    except (ValueError, RecursionError) as error:
        raise ReleaseCiError('Invalid release CI metadata.') from error
    if not isinstance(payload, dict) or not isinstance(payload.get('workflow_runs'), list):
        raise ReleaseCiError('Missing release CI runs.')
    matches = []
    for row in payload['workflow_runs']:
        if not isinstance(row, dict):
            raise ReleaseCiError('Invalid CI run metadata.')
        repository = row.get('repository')
        if not isinstance(repository, dict):
            raise ReleaseCiError('Invalid CI repository identity.')
        if (row.get('head_sha') != commit or row.get('event') != 'push' or row.get('head_branch') != 'main'
                or repository.get('full_name') != REPOSITORY):
            continue
        if type(row.get('id')) is not int or row['id'] <= 0:
            raise ReleaseCiError('Invalid CI run identity.')
        matches.append(row)
    if not matches:
        raise ReleaseCiError('No matching CI run for the release commit. Run CI before publishing.')
    latest = max(matches, key=lambda row: row['id'])
    if latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
        raise ReleaseCiError('The latest exact-commit CI run has not passed. Wait for green CI, then rerun release.')
    return {'commit': commit, 'run_id': latest['id'], 'status': 'success'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_ci(args.expected_commit), sort_keys=True))
    except ReleaseCiError as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
