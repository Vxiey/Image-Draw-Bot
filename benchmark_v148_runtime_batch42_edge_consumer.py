"""Measure the complete public edge operation on real luminance/Lab inputs.

This follow-up retains the initial whole-analysis report unchanged. It resolves
whether the bounded helper still benefits the public validation/route/Stop
wrapper and the noncontiguous Lab-channel layout used by AccuracyEvaluator.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as current_gpu
from benchmark_v148_runtime_batch42 import BASELINE, ROOT, compare, current, historical


def main():
    before = historical('ImageGradients.py')
    baseline_gpu = historical('UniversalGpuAcceleration.py')
    source_path = ROOT / 'assets' / 'paint-tools-reference.png'
    rows = []
    with closing(Image.open(source_path)) as original, closing(original.convert('RGB')) as rgb:
        for size in ((384, 256), (1536, 1024)):
            with closing(rgb.resize(size, Image.Resampling.NEAREST)) as source, \
                    closing(source.convert('L')) as gray:
                luminance = np.asarray(gray, dtype=np.float32) / np.float32(255)
                lab, _ = baseline_gpu.oklab_array(np.asarray(source), gpu_mode='CPU')
                for kind, values in (('dense_luminance', luminance), ('strided_lab', lab[..., 0])):
                    def operation(module):
                        executor = baseline_gpu if module is before else current_gpu
                        return executor.edge_magnitude(values, gpu_mode='CPU')
                    row = compare(f'complete_edge_{kind}_{size[0]}x{size[1]}', operation,
                                  before, baseline_gpu, pairs=4)
                    row.update(input_strides=values.strides, input_contiguous=bool(values.flags.c_contiguous))
                    rows.append(row)
    files = ('ImageGradients.py', 'UniversalGpuAcceleration.py',
             'benchmark_v148_runtime_batch42.py', Path(__file__).name)
    report = {
        'baseline_commit': BASELINE,
        'baseline_tree': subprocess.check_output(['git', 'rev-parse', f'{BASELINE}^{{tree}}'], cwd=ROOT, text=True).strip(),
        'method': 'Four alternating AB/BA elapsed pairs and separate traced peaks, exact complete array/route equality. Each side uses its actual historical/current public edge_magnitude and matching gradient implementation.',
        'scope': 'Public CPU edge operation including validation, route selection and completion. Caller-owned dense luminance and real CPU Lab channels are prepared outside the call. This does not replace or invalidate the initial complete Accuracy/Importance/PixelMap observations.',
        'python': sys.version, 'numpy': np.__version__,
        'fixture': {'path': source_path.relative_to(ROOT).as_posix(),
                    'sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()},
        'sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
        'cases': rows,
    }
    (ROOT / 'docs' / 'v148-batch42-runtime-edge-consumer.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps([{key: row[key] for key in ('name', 'before_median_ms', 'after_median_ms',
                     'before_traced_peak_bytes', 'after_traced_peak_bytes', 'exact_complete_output')}
                     for row in rows], indent=2))


if __name__ == '__main__':
    main()
