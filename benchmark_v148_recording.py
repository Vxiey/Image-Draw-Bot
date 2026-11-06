"""Paired actual record_screen workers; deterministic capture, no screen access."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import queue
import statistics
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import PIL
from PIL import Image, ImageChops, ImageSequence

import ScreenRecording


BASELINE = '8a9c848b9dd0f2c4738aee729dace75be2a5778d'


def method(source):
    tree = ast.parse(source)
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'DrawBotApp')
    function = next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == 'record_screen')
    return function


def main():
    before = subprocess.check_output(['git', 'show', BASELINE + ':DrawBot.py'], text=True)
    before_helper = subprocess.check_output(['git', 'show', BASELINE + ':ScreenRecording.py'], text=True)
    helper = {'__name__': 'baseline_screen_recording'}
    exec(compile(before_helper, 'baseline-ScreenRecording.py', 'exec'), helper)
    source = Path('DrawBot.py').read_text(encoding='utf-8')
    nodes = {'baseline': method(before), 'current': method(source)}
    saves = {'baseline': helper['save_gif_atomic'], 'current': ScreenRecording.save_gif_atomic}
    rng = np.random.default_rng(14807)
    palette = rng.integers(0, 256, (16, 3), dtype=np.uint8)
    y, x = np.indices((500, 800))
    base = Image.fromarray(palette[(x // 40 + y // 40) % len(palette)])

    def run(label, changing):
        clock = SimpleNamespace(now=0.0, captures=0)
        class Stop:
            def is_set(self): return clock.captures >= 100
            def wait(self, seconds): clock.now += seconds; return False
        def capture(area):
            clock.captures += 1; clock.now += .25949
            return ImageChops.offset(base, clock.captures * 7, 0) if changing else base.copy()
        observed = {}; jobs = []
        app = SimpleNamespace(corners=[(0, 0), base.size], area=lambda: (0, 0, *base.size),
            stop=Stop(), events=queue.Queue(), begin_worker=lambda activity, work: jobs.append(work))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'recording.gif'
            namespace = {'Path': Path, 'time': SimpleNamespace(monotonic=lambda: clock.now),
                'grab_area': capture, 'filedialog': SimpleNamespace(asksaveasfilename=lambda **kwargs: str(destination))}
            exec(compile(ast.Module(body=[nodes[label]], type_ignores=[]), 'record_screen.py', 'exec'), namespace)
            namespace['record_screen'](app)
            def save(path, frames, durations):
                observed['retained_frames'] = len(frames)
                observed['retained_pixel_payload_bytes'] = sum(frame.width * frame.height for frame in frames)
                observed['raw_duration_ms'] = sum(durations)
                return saves[label](path, frames, durations)
            with patch.object(ScreenRecording, 'save_gif_atomic', side_effect=save):
                start = time.perf_counter()
                jobs[0]()
                observed['worker_seconds'] = time.perf_counter() - start
            # Decode/compare outside the measured worker. Timing differences are
            # intentional: AY02 removes per-frame integer/GIF truncation.
            digest = hashlib.sha256(); durations = []
            with Image.open(destination) as gif:
                for frame in ImageSequence.Iterator(gif):
                    with frame.convert('RGB') as rgb: digest.update(rgb.tobytes())
                    durations.append(frame.info['duration'])
            observed['decoded_frame_count'] = len(durations)
            observed['decoded_pixels_sha256'] = digest.hexdigest()
            observed['decoded_duration_ms'] = sum(durations)
            return observed

    records = {}
    try:
        for workload, changing in (('unchanged', False), ('changing', True)):
            warmup = {label: run(label, changing) for label in nodes}
            assert warmup['baseline']['decoded_pixels_sha256'] == warmup['current']['decoded_pixels_sha256']
            pairs = []
            for index in range(3):
                order = tuple(nodes) if index % 2 == 0 else tuple(reversed(nodes))
                pair = {label: run(label, changing) for label in order}
                assert pair['baseline']['decoded_pixels_sha256'] == pair['current']['decoded_pixels_sha256']
                assert pair['baseline']['decoded_frame_count'] == pair['current']['decoded_frame_count']
                assert abs(pair['current']['decoded_duration_ms'] - 25_949) <= 5
                pairs.append(pair)
            medians = {label: {key: statistics.median(pair[label][key] for pair in pairs)
                for key in ('worker_seconds', 'retained_frames', 'retained_pixel_payload_bytes',
                            'decoded_duration_ms', 'decoded_frame_count')} for label in nodes}
            records[workload] = {'warmup': warmup, 'pairs': pairs, 'medians': medians}
    finally:
        base.close()
    result = {'baseline_commit': BASELINE, 'python': platform.python_version(), 'pillow': PIL.__version__,
        'numpy': np.__version__, 'frames': 100, 'capture_size': [800, 500],
        'clock_step_ms': 259.49, 'scope': 'Actual record_screen worker with simulated capture/clock; no desktop or native input. Retained P pixel payload is width*height bytes, excluding palette/core allocator overhead, capture/comparison/GIF scratch and Python objects; process RSS is not measured.',
        'source_hashes': {label + '_record_screen_ast': hashlib.sha256(ast.dump(node).encode()).hexdigest()
                          for label, node in nodes.items()},
        'helper_hashes': {'baseline': hashlib.sha256(before_helper.encode()).hexdigest(),
                         'current': hashlib.sha256(Path('ScreenRecording.py').read_bytes()).hexdigest()},
        'results': records}
    Path('docs/v148-batch07-recording-benchmarks.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value['medians'] for key, value in records.items()}, indent=2))


if __name__ == '__main__':
    main()
