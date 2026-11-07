"""Compare the complete bounded JSON reader on actual files and consumers.

The historical RuntimePaths module and every imported reader alias used by the
recorded consumers are installed together. --verify-only compares outputs and
work without timings; final six-pair timing requires a quiet coordinated window.
"""
import argparse
from contextlib import ExitStack, contextmanager
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

import DrawTimeCalibration as timing
import CorrectionHistory as correction
import ExactColorTools as exact
import RealSpeedBudget as speed
import ResourceScheduler as scheduler
import RuntimePaths as runtime
import SessionRecovery as recovery
from benchmark_v148_image_workflow import old_module
from benchmark_v148_rendering_batch21_calibration import comparable, EXCLUDED
from test_v148_platform_batch23_json_reader import ConsumerFixture, file_reads, CHUNK_BYTES


ROOT = Path(__file__).resolve().parent
BASELINE = '5c32b6883c454268e06e199a8f15264ca9ec26e9'
ALIASES = (timing, speed, scheduler, recovery, exact, correction)
MIB = 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def linked(reader):
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {'RuntimePaths': reader}))
        for module in ALIASES:
            stack.enter_context(patch.object(module, 'read_json', new=reader.read_json))
        yield


def outcome(value, error):
    if error is None:
        return {'status': 'value', 'value': comparable(value)}
    result = {'status': 'error', 'class': type(error).__name__, 'message': str(error)}
    if isinstance(error, UnicodeDecodeError):
        result.update(encoding=error.encoding, start=error.start, end=error.end,
                      reason=error.reason, input_sha256=hashlib.sha256(error.object).hexdigest())
    elif isinstance(error, json.JSONDecodeError):
        result.update(pos=error.pos, line=error.lineno, column=error.colno,
                      document_sha256=hashlib.sha256(error.doc.encode('utf-8')).hexdigest())
    return result


class Operation:
    def __init__(self, reader, call, paths, *, close=lambda _result: None):
        self.reader, self.call, self.paths, self.close = reader, call, paths, close

    def run(self, *, elapsed=False, trace=False):
        value = error = None
        evidence = {}
        with linked(self.reader):
            if trace:
                if tracemalloc.is_tracing():
                    raise RuntimeError('Reader measurement requires its own tracemalloc session.')
                gc.collect()
                tracemalloc.start()
            try:
                started = time.perf_counter() if elapsed else None
                try:
                    value = self.call()
                except Exception as caught:
                    error = caught
                if elapsed:
                    evidence['elapsed_ms'] = (time.perf_counter() - started) * 1000.
                if trace:
                    retained, peak = tracemalloc.get_traced_memory()
                    evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                    tracemalloc.stop()
                return outcome(value, error), evidence
            finally:
                if trace and tracemalloc.is_tracing():
                    tracemalloc.stop()
                self.close(value)
                # Keep neither a comparison result nor an error frame between
                # benchmark operations. The trace includes a caught error while
                # measuring the deliberate size-rejection control on both sides.
                value = error = None

    def work(self):
        with file_reads(self.paths) as (reads, handles):
            result, _evidence = self.run()
        if not all(stream.closed for stream in handles):
            raise AssertionError('A reader left a real input file open.')
        return {'output_sha256': digest(result), 'files_opened': len(handles),
            'read_calls': len(reads), 'max_requested_bytes': max((r['requested'] for r in reads), default=0),
            'total_returned_bytes': sum(r['returned'] for r in reads),
            'reads': [{'file': row['path'].name, 'requested': row['requested'],
                       'returned': row['returned']} for row in reads]}


def direct_operation(reader, path, **kwargs):
    return Operation(reader, lambda: reader.read_json(path, **kwargs), [path])


def parity_cases():
    cases = []
    values = (None, True, False, 0, -0.0, 123456789012345678901234567890, 'é漢🐈',
              {'a': [0, None, True, 'é'], 'b': {'x': 1.25}})
    for index, value in enumerate(values):
        raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        for bom in (b'', b'\xef\xbb\xbf'):
            cases.append((f'value-{index}-bom-{bool(bom)}', bom + raw, {}))
    for limit in (0, 1, 2, 7, CHUNK_BYTES - 1, CHUNK_BYTES, CHUNK_BYTES + 1, 2 * CHUNK_BYTES):
        for delta in (-1, 0, 1):
            length = max(0, limit + delta)
            raw = b'0' + b' ' * (length - 1) if length else b''
            cases.append((f'limit-{limit}-delta-{delta}', raw, {'max_bytes': limit}))
    for text in ('é', '漢', '🐈'):
        for bom in (b'', b'\xef\xbb\xbf'):
            padding = CHUNK_BYTES - len(bom) - len(b'{"x":"') - 1
            raw = bom + json.dumps({'x': 'a' * padding + text},
                                    ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            cases.append((f'utf8-boundary-{ord(text)}-bom-{bool(bom)}', raw, {'max_bytes': len(raw)}))
    invalid = (b'', b'{', b'{"x":0,"x":1}', b'{"x":NaN}', b'{"x":Infinity}',
               b'{"x":1e309}', b'0\x00', b'0 trailing', b'\xff', b'\xff\xfe{\x00}\x00',
               b'"' + b'a' * CHUNK_BYTES + b'\xc3"', b'{"a":\n "b"',
               b'[' * 3000 + b'0' + b']' * 3000)
    for index, raw in enumerate(invalid):
        cases.append((f'invalid-{index}', raw, {}))
    for depth in (0, 1, 2, 31, 32, 33, 40):
        cases.append((f'default-depth-{depth}', b'[' * depth + b'0' + b']' * depth, {}))
    for max_items in (0, 1, 2, 4, 5, 6):
        cases.append((f'nodes-{max_items}', b'{"a":[0,1,2]}', {'max_items': max_items}))
    for max_depth in (0, 1, 2, 3):
        cases.append((f'explicit-depth-{max_depth}', b'{"a":[0]}', {'max_depth': max_depth}))
    # These large container cases retain the reader's node checks, independently
    # of both the old and new input-allocation strategies.
    cases.append(('nodes-accepted-100000', b'[' + b'0,' * 99998 + b'0]', {}))
    cases.append(('nodes-rejected-100001', b'[' + b'0,' * 99999 + b'0]', {}))
    return cases


def historical_parity(old, directory):
    path = Path(directory) / 'historical-reader.json'
    rows = []
    for name, raw, kwargs in parity_cases():
        path.write_bytes(raw)
        outputs = [direct_operation(reader, path, **kwargs).run()[0] for reader in (old, runtime)]
        if outputs[0] != outputs[1]:
            raise AssertionError(('Historical reader output/error mismatch', name, outputs))
        if path.read_bytes() != raw:
            raise AssertionError('Read-only parsing changed its input.')
        rows.append({'case': name, 'input_bytes': len(raw), 'input_sha256': hashlib.sha256(raw).hexdigest(),
                     'parameters': kwargs, 'status': outputs[0]['status'], 'output_sha256': digest(outputs[0])})
    path.unlink()
    outputs = [direct_operation(reader, path).run()[0] for reader in (old, runtime)]
    if outputs[0] != outputs[1] or outputs[0].get('class') != 'FileNotFoundError':
        raise AssertionError('Historical missing-file semantics changed.')
    rows.append({'case': 'missing-file', 'status': 'error', 'output_sha256': digest(outputs[0])})
    return {'complete_reader_pairs': len(rows), 'exact_output_and_error_parity': True, 'cases': rows}


def paired(before, after, repeats):
    operations = {'before': before, 'after': after}
    expected, _ = before.run()
    actual, _ = after.run()
    if actual != expected:
        raise AssertionError('Complete workload warm/output parity failed.')
    samples = {side: [] for side in operations}
    orders = []
    for pair in range(repeats):
        order = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
        orders.append(list(order))
        for side in order:
            actual, evidence = operations[side].run(elapsed=True)
            if actual != expected:
                raise AssertionError(('Complete timed output parity failed', side))
            samples[side].append(evidence['elapsed_ms'])
    row = {'orders': orders, 'exact_output_parity': True, 'output_sha256': digest(expected)}
    for side, operation in operations.items():
        row[side + '_samples_ms'] = samples[side]
        row[side + '_median_ms'] = statistics.median(samples[side])
        actual, evidence = operation.run(trace=True)
        if actual != expected:
            raise AssertionError(('Complete traced output parity failed', side))
        row.update({side + '_' + key: value for key, value in evidence.items()})
    return row


def add_workload(report, name, operations, parameters, *, repeats, verify_only, error_class=None):
    expected = operations[0].run()[0]
    actual = operations[1].run()[0]
    if expected != actual:
        raise AssertionError(('Complete workload output parity failed', name))
    if error_class is None and expected['status'] != 'value':
        raise AssertionError(('Expected successful workload returned an error', name, expected))
    if error_class is not None and expected.get('class') != error_class:
        raise AssertionError(('Expected rejection did not occur', name, expected))
    row = ({'exact_output_parity': True, 'output_sha256': digest(expected)} if verify_only
           else paired(*operations, repeats))
    for side, operation in zip(('before', 'after'), operations):
        observed = operation.work()
        if observed['output_sha256'] != row['output_sha256']:
            raise AssertionError(('Read observation changed output', name, side))
        row[side + '_work'] = observed
    if row['before_work']['total_returned_bytes'] != row['after_work']['total_returned_bytes']:
        raise AssertionError(('Regular-file byte consumption changed', name))
    if row['after_work']['max_requested_bytes'] > CHUNK_BYTES:
        raise AssertionError(('A new reader requested its whole byte allowance', name))
    row['parameters'] = parameters
    report['measurements'][name] = row


def file_snapshot(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA samples.')
    old = old_module('RuntimePaths', revision)
    original = subprocess.check_output(['git', 'show', f'{revision}:RuntimePaths.py'], cwd=ROOT)
    hashes = source_hashes()
    report = {'baseline': revision, 'historical_module_sha256': {'RuntimePaths': hashlib.sha256(original).hexdigest()},
        'source_sha256': hashes, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'verify_only': verify_only, 'repeats': None if verify_only else repeats,
        'historical_linkage': 'Complete historical RuntimePaths is installed for local imports and all six recorded consumer aliases: DrawTimeCalibration, RealSpeedBudget, ResourceScheduler, SessionRecovery, ExactColorTools and CorrectionHistory. All consumer products, including R2101 planning observation, are identical current dependencies on both sides. The public Pixel planner uses no historical/new reader mixture. Its optional exact-color controls and correction-history files remain absent in the original fixture; those two readers therefore preserve their ordinary missing-file fallback, without invented extra history.',
        'method': ('Complete output and error parity on regular files; independent read-size/count observations; '
            + ('no elapsed or allocation measurement in verification-only mode. ' if verify_only else
               f'{repeats} balanced AB/BA elapsed pairs and separate tracemalloc calls after garbage collection. ')
            + 'Fixture setup, module/alias linking, normalization/hashing and owned-image disposal are outside measured calls.'),
        'timing_scope': 'One actual reader, public consumer or complete make_plan invocation per sample. Files are already in the operating system cache. No disk-throughput, startup, native-input, GPU or whole-application speed claim.',
        'memory_scope': 'Separate Python traced peak and retained-with-result of one complete call. This is not total process RSS or most native Pillow memory. Large near-limit files explicitly measure growing-accumulator overhead; no universal peak reduction is assumed.',
        'bounded_read_contract': 'One open descriptor, requests at most 65536 bytes and cumulative limit+1 returned bytes; positive short reads continue; empty bytes indicate EOF. Small valid files normally add one EOF read. Exact-limit files also need a final sentinel/EOF read. No stat/seek/reopen is used by the product reader.',
        'fixture_source': 'Real timing, speed, scheduler and recovery files come from unchanged production writers. The complete Paint Pixel plan reads the same real calibrated timing file; no filler history is added. Separate direct large-file controls contain valid JSON at their declared boundary.',
        'excluded_output_fields': sorted('/'.join(path) for path in EXCLUDED),
        'error_scope': 'Historical comparisons include complete error class/message and UTF/JSON position/input digest. Mutation, positive-short-read, retained-IO/MemoryError and invalid-index contracts have focused regressions; concurrent mutation interleavings are not claimed byte-for-byte identical to a single old read.',
        'measurements': {}}
    with tempfile.TemporaryDirectory(prefix='batch23-reader-parity-') as directory:
        report['historical_parity'] = historical_parity(old, directory)
    with ConsumerFixture() as fixture:
        optional_paths = (('ExactColorTools', Path(exact.file_for('microsoft-paint'))),
                          ('CorrectionHistory', correction._resolved_path(fixture.pixel)))
        report['public_plan_optional_files'] = [
            {'consumer': name, 'file': path.name, 'exists': path.exists()} for name, path in optional_paths]
        if any(row['exists'] for row in report['public_plan_optional_files']):
            raise AssertionError('The original optional-missing public-plan fixture changed.')
        all_paths = sorted(fixture.directory.rglob('*.json'))
        files_before = file_snapshot(all_paths)
        source_before = fixture.source.tobytes(), dict(fixture.source.info)
        for name, (call, paths) in fixture.cases().items():
            value = call()
            try:
                if value is None:
                    raise AssertionError(('A real seeded consumer used its fallback', name))
                if name == 'timing_correction' and not value.get('learned'):
                    raise AssertionError('The timing consumer did not read learned calibration.')
                if name == 'public_paint_pixel_plan' and value.get('count', 0) <= 0:
                    raise AssertionError('The public planner did not build any paths.')
            finally:
                fixture.close_result(name, value)
            operations = [Operation(reader, call, paths,
                close=lambda result, name=name: fixture.close_result(name, result)) for reader in (old, runtime)]
            parameters = {'actual_consumer': name, 'observed_files': {
                path.name: {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in paths}}
            if name == 'public_paint_pixel_plan':
                parameters.update(source_size=list(fixture.source.size), source_mode=fixture.source.mode,
                                  policy='Paint / Pixel Accurate / CPU / Unlimited')
            add_workload(report, name, operations, parameters, repeats=repeats, verify_only=verify_only)
        if file_snapshot(all_paths) != files_before or set(fixture.directory.rglob('*.json')) != set(all_paths):
            raise AssertionError('Actual consumer comparison changed its persisted files.')
        if (fixture.source.tobytes(), fixture.source.info) != source_before:
            raise AssertionError('Actual public planning changed its borrowed source.')
    with tempfile.TemporaryDirectory(prefix='batch23-reader-large-') as directory:
        path = Path(directory) / 'large.json'
        scenarios = (
            ('small_file_eight_mib_allowance', json.dumps({'text': 'valid state ' * 300}).encode(), 8 * MIB, None),
            ('ascii_string_exact_four_mib', b'"' + b'x' * (4 * MIB - 2) + b'"', 4 * MIB, None),
            ('utf8_string_near_four_mib', ('"' + '🐈' * ((4 * MIB - 2) // 4) + '"').encode(), 4 * MIB, None),
            ('whitespace_exact_eight_mib', b'0' + b' ' * (8 * MIB - 1), 8 * MIB, None),
            ('one_byte_over_eight_mib', b'0' + b' ' * (8 * MIB), 8 * MIB, 'ValueError'),
        )
        for name, content, limit, error_class in scenarios:
            path.write_bytes(content)
            operations = [direct_operation(reader, path, max_bytes=limit) for reader in (old, runtime)]
            parameters = {'actual_consumer': 'RuntimePaths.read_json', 'file_bytes': len(content),
                'file_sha256': hashlib.sha256(content).hexdigest(), 'max_bytes': limit,
                'expected_error_class': error_class}
            add_workload(report, name, operations, parameters,
                         repeats=repeats, verify_only=verify_only, error_class=error_class)
            if path.read_bytes() != content:
                raise AssertionError('A direct reader changed its input file.')
    final_hashes = source_hashes()
    report['source_unchanged'] = hashes == final_hashes
    if not report['source_unchanged']:
        changed = sorted(name for name in hashes.keys() | final_hashes.keys()
                         if hashes.get(name) != final_hashes.get(name))
        report['source_changed_paths'] = changed
        if not verify_only or 'RuntimePaths.py' in changed:
            raise AssertionError(('Source changed during reader measurement', changed))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch23-json-reader-benchmarks.json')
    args = parser.parse_args()
    report = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'historical_reader_pairs': report['historical_parity']['complete_reader_pairs'],
        'workloads': len(report['measurements']), 'source_unchanged': report['source_unchanged'],
        'verify_only': args.verify_only}))


if __name__ == '__main__':
    main()
