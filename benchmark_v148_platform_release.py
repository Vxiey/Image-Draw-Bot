"""Reproduce the source-hygiene traversal measurement using local synthetic data.

Reads the exact historical function from Git. It does not install dependencies,
open network connections, or inspect the developer's private build directories.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc

from ReleaseCandidateHardening import find_one_shot_source_files

BASELINE = '5f3fcfb5c4519e5ed1b9b770ba951918819d725d'


def historical_check():
    repository = Path(__file__).resolve().parent
    source = subprocess.run(['git', 'show', BASELINE + ':ReleaseCandidateHardening.py'],
                            cwd=repository, check=True, capture_output=True, text=True).stdout
    tree = ast.parse(source)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'find_one_shot_source_files')
    namespace = {'Path': Path, 're': re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<historical hygiene function>', 'exec'), namespace)
    return namespace['find_one_shot_source_files']


def measure(check, root, expected, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = check(root)
        samples.append(time.perf_counter() - start)
        if result != expected:
            raise AssertionError('The measured source findings changed.')
    return samples


def memory_peak(check, root, expected):
    tracemalloc.start()
    try:
        if check(root) != expected:
            raise AssertionError('The measured source findings changed.')
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def run(repeats=5):
    before, after = historical_check(), find_one_shot_source_files
    expected = ['.github/workflows/validate-once.yml', 'patch_once.py']
    with tempfile.TemporaryDirectory(prefix='source-hygiene-benchmark-') as temporary:
        root = Path(temporary)
        for private in ('.git', '.build-venv', 'dist'):
            for directory in range(20):
                folder = root / private / f'package-{directory:02d}'
                folder.mkdir(parents=True)
                for number in range(100):
                    (folder / f'file-{number:03d}.py').write_text('# synthetic private dependency\n', encoding='utf-8')
        for directory in range(8):
            folder = root / f'module-{directory:02d}'
            folder.mkdir()
            for number in range(50):
                (folder / f'file-{number:03d}.py').write_text('# synthetic source\n', encoding='utf-8')
        for relative in expected:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# intentional source hygiene finding\n', encoding='utf-8')
        # Warm imports and file metadata; alternate paired timings. Memory is
        # measured separately, so tracemalloc does not distort the time ratio.
        measure(before, root, expected, 1)
        measure(after, root, expected, 1)
        samples = {'before': [], 'after': []}
        for iteration in range(repeats):
            pair = (('before', before), ('after', after))
            if iteration % 2:
                pair = tuple(reversed(pair))
            for label, check in pair:
                samples[label].extend(measure(check, root, expected, 1))
        peaks = {'before': memory_peak(before, root, expected),
                 'after': memory_peak(after, root, expected)}
    medians = {label: statistics.median(values) for label, values in samples.items()}
    return {
        'schema': 1, 'baseline_commit': BASELINE,
        'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'fixture': {'included_files': 402, 'excluded_private_files': 6000,
                    'private_roots': ['.git', '.build-venv', 'dist'], 'expected_findings': expected},
        'seconds_samples': samples, 'seconds_median': medians,
        'python_allocation_peak_bytes': peaks,
        'median_time_ratio_before_over_after': medians['before'] / medians['after'],
        'limitations': 'Synthetic local filesystem with warmed metadata; Python allocation peak is not process RSS. This measures only source-hygiene traversal, not build or application runtime.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 1000:
        parser.error('--repeats must be in 1..1000')
    result = run(args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'seconds_median': result['seconds_median'],
                      'python_allocation_peak_bytes': result['python_allocation_peak_bytes']}))


if __name__ == '__main__':
    main()
