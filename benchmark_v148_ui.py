import argparse
import gc
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
import time
import tracemalloc

parser = argparse.ArgumentParser()
parser.add_argument('--source-tree', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(args.source_tree).resolve()))
from PIL import Image
import ProfilePolish
import WordGuesser
import PreviewLayers
import CanvasDropPayload


def measure(call, repeat=5):
    call()
    times = []
    for _ in range(repeat):
        gc.collect()
        start = time.perf_counter(); result = call(); times.append(time.perf_counter()-start)
    gc.collect(); tracemalloc.start(); result = call(); _current, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    return {'seconds_median': statistics.median(times), 'seconds_samples': times,
            'peak_traced_bytes': peak, 'result': result}


def preset():
    for _ in range(30000):
        result = ProfilePolish.profile_release_preset('Gartic Phone')
    return result.profile_key

rng = random.Random(20261106)
words = tuple(''.join(rng.choice('abcdefghijklmnopqrstuvxyz') for _ in range(rng.randrange(4, 17))) for _ in range(20000))
queries = tuple(('', str(4+i%13)) if i%2 == 0 else ('a'+'_'*(3+i%13), '') for i in range(100))


def dictionary():
    results = [WordGuesser.find_candidates(words, pattern, length) for pattern, length in queries]
    return hashlib.sha256(json.dumps(results).encode()).hexdigest()

source = Image.new('RGBA', (320, 200), (30, 60, 90, 120))
path = tuple((index % 900, (index*13) % 600) for index in range(200000))


def previews():
    images = PreviewLayers.build_auxiliary_previews(source, source.size, [], [(10, 40, 90)],
        lambda x, y: (x, y), 1, {'_preview_safety_groups': [[path]], '_preview_plan': True,
        '_preview_stroke_map_limit': 200, 'preview_safety_meta': {'canvas_guard': {'area': [0, 0, 900, 600]}}})
    hashes = {name: hashlib.sha256(image.tobytes()).hexdigest() for name, image in images.items()}
    for image in images.values(): image.close()
    return hashes

payload = '\n'.join(f'https://example.com/page-{n:06d}' for n in range(16000)) + '\nhttps://example.com/a.png'


def drops():
    result = CanvasDropPayload.parse_canvas_drop(payload)
    return result.source

results = {'source_tree': args.source_tree, 'scope': 'CPU-only helper microbenchmarks; no real desktop input or GPU timing',
           'preset_30000': measure(preset), 'dictionary_20000_words_100_queries': measure(dictionary, 3),
           'preview_200000_points': measure(previews, 3), 'drop_16001_urls': measure(drops, 3)}
Path(args.output).write_text(json.dumps(results, indent=2)+'\n')
print(json.dumps(results, indent=2))
