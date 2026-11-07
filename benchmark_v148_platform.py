"""Reproduce installer-cache I/O savings; no network or executables are run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import types

import UpdateCenter

BASELINE = 'f59a57c6fc1eef1ace07e872ba50ed834e1bb924'


def baseline_module(root):
    source = subprocess.run(['git', 'show', f'{BASELINE}:UpdateCenter.py'], cwd=root,
                            check=True, capture_output=True, text=True).stdout
    name = '_v148_update_baseline'
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name, 'exec'), module.__dict__)
    return module


class Response:
    status_code = 200
    url = 'https://release-assets.githubusercontent.com/synthetic'

    def __init__(self, data, counters):
        self.data, self.counters = data, counters
        self.headers = {'Content-Length': str(len(data))}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for start in range(0, len(self.data), chunk_size):
            block = self.data[start:start + chunk_size]
            self.counters['transport_body_bytes'] += len(block)
            yield block

    def close(self):
        pass


def measure(module, data, requests_per_round):
    digest = hashlib.sha256(data).hexdigest()
    name = 'ImageDrawBot-99.0.0-Windows-x64-Setup.exe'
    asset = module.installer_asset({'tag_name': 'v99.0.0', 'assets': [{
        'name': name, 'size': len(data), 'digest': 'sha256:' + digest,
        'browser_download_url': f'https://github.com/Vxiey/Image-Draw-Bot/releases/download/v99.0.0/{name}',
    }]})
    counters = {'transport_calls': 0, 'transport_body_bytes': 0}
    def get(*args, **kwargs):
        counters['transport_calls'] += 1
        return Response(data, counters)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        started = time.perf_counter()
        paths = [Path(module.download_installer(asset, directory=root, request_get=get))
                 for _ in range(requests_per_round)]
        elapsed = time.perf_counter() - started
        # Every returned result, including a reused path, must have identical
        # public installer bytes. Verification is outside the timing interval.
        assert all(path.read_bytes() == data for path in paths)
        executables = list(root.rglob('*.exe'))
        counters.update(elapsed_seconds=elapsed, unique_installer_files=len(executables),
                        retained_installer_bytes=sum(path.stat().st_size for path in executables),
                        output_sha256=digest)
    return counters


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('docs/v148-batch06-platform-benchmarks.json'))
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    baseline = baseline_module(root)
    # Synthetic bytes have only the MZ magic used by the downloader's shallow
    # format check. They are never submitted to an OS executable loader.
    data = b'MZ' + bytes(range(256)) * (8 * 1024 * 1024 // 256)
    requests_per_round, rounds = 3, 5
    measure(baseline, data, requests_per_round)
    measure(UpdateCenter, data, requests_per_round)
    results = {'before': [], 'after': []}
    for index in range(rounds):
        pairs = [('before', baseline), ('after', UpdateCenter)]
        if index % 2:
            pairs.reverse()
        for label, module in pairs:
            results[label].append(measure(module, data, requests_per_round))
    report = {
        'baseline_commit': BASELINE,
        'python': platform.python_version(), 'platform': platform.system(),
        'fixture': {'bytes': len(data), 'requests_per_round': requests_per_round,
                    'rounds': rounds, 'alternating_paired_order': True, 'warmup_rounds': 1},
        'output_parity': 'Every returned installer is byte-for-byte equal to the same synthetic input.',
        'measurement_limits': ('In-process transport, local temporary filesystem and warm imports. '
                               'No network latency, Windows execution or antivirus performance is measured. '
                               'Cache hits still read and hash the entire file. Timing excludes independent parity checks.'),
        'runs': results,
        'median_seconds': {name: statistics.median(row['elapsed_seconds'] for row in rows)
                           for name, rows in results.items()},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(arguments.output), 'median_seconds': report['median_seconds'],
                      'before': results['before'][0], 'after': results['after'][0]}, indent=2))


if __name__ == '__main__':
    main()
