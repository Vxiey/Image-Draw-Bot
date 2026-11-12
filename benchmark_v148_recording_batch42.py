"""Complete append_recorded_frame comparisons on existing captured-image data."""
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time
import tracemalloc

import PIL
from PIL import Image

import ScreenRecording


BASELINE = 'e33fa67d17e3c33ccda8e736e7e16c2582d9fc06'


def main():
    raw = subprocess.check_output(['git', 'show', BASELINE + ':ScreenRecording.py'])
    namespace = {'__name__': 'historical_screen_recording'}
    exec(compile(raw, 'historical-ScreenRecording.py', 'exec'), namespace)
    methods = {'before': namespace['append_recorded_frame'], 'after': ScreenRecording.append_recorded_frame}
    asset = Path('assets/image-draw-bot-app-screenshot.png')
    rows = {}
    with Image.open(asset) as source:
        for name, size, mode in (('capture_palette', (800, 500), 'P'),
                                 ('small_palette', (256, 256), 'P'),
                                 ('large_rgba_api_control', (1920, 1080), 'RGBA')):
            with source.resize(size) as resized:
                previous = resized.quantize(colors=128) if mode == 'P' else resized.convert(mode)
            with previous:
                for changing in (False, True):
                    with previous.copy() as frame:
                        if changing:
                            value = frame.getpixel((0, 0))
                            frame.putpixel((0, 0), (value + 1) % 128 if mode == 'P'
                                           else ((value[0] + 1) % 256, *value[1:]))
                        expected = frame.tobytes() != previous.tobytes()
                        def run(label):
                            frames, durations = [previous], [250.25]
                            result = methods[label](frames, durations, frame, 249.75)
                            assert result == expected
                            assert durations == ([250.25, 249.75] if expected else [500])
                            assert len(frames) == (2 if expected else 1)
                            assert frames[0] is previous
                        for label in methods: run(label)
                        pairs = []
                        for pair in range(6):
                            samples = {}
                            order = tuple(methods) if pair % 2 == 0 else tuple(reversed(methods))
                            for label in order:
                                started = time.perf_counter()
                                for _ in range(20): run(label)
                                samples[label] = (time.perf_counter() - started) / 20
                            pairs.append(samples)
                        allocation = {}
                        for label in methods:
                            tracemalloc.start()
                            run(label)
                            current, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            allocation[label] = {'retained_traced_bytes': current, 'peak_traced_bytes': peak}
                        rows[name + ('_changing' if changing else '_static')] = {
                            'size': size, 'mode': mode, 'changed_first_pixel': changing,
                            'pairs_seconds': pairs,
                            'median_seconds': {label: statistics.median(row[label] for row in pairs) for label in methods},
                            'allocations': allocation, 'exact_retention_and_duration_parity': True}
    report = {'baseline_commit': BASELINE, 'python': platform.python_version(), 'pillow': PIL.__version__,
              'scope': 'Whole public append_recorded_frame call. Capture P mode/size is the real recorder bound; RGBA is an independent public-API control. Excludes capture, quantization, GIF encoding, physical desktop and process RSS. Tracemalloc does not measure Pillow core crop storage; each pair additionally owns at most two 65536-pixel strip cores.',
              'asset': str(asset), 'asset_sha256': hashlib.sha256(asset.read_bytes()).hexdigest(),
              'source_sha256': {'before': hashlib.sha256(raw).hexdigest(),
                                'after': hashlib.sha256(Path('ScreenRecording.py').read_bytes()).hexdigest()},
              'results': rows}
    Path('docs/v148-batch42-recording-benchmark.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({name: {'median_seconds': row['median_seconds'], 'allocations': row['allocations']}
                      for name, row in rows.items()}, indent=2))


if __name__ == '__main__':
    main()
