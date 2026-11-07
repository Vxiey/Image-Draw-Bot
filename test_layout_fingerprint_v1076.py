import unittest
import tempfile
import json
from pathlib import Path
from PIL import Image

from LayoutFingerprintV2 import record_layout, try_restore, load_cache, zoom_signature


def _meta():
    return {'client_rect': (100, 200, 900, 700), 'dpi': 96}


def _palette():
    return [
        {'name': f'C{i}', 'position': [140+i*24, 660], 'rgb': [20+i*15, 30+i*8, 40+i*5]}
        for i in range(8)
    ]


def _screen():
    image = Image.new('RGB', (800, 500), (240,240,240))
    for i, item in enumerate(_palette()):
        x = item['position'][0]-100; y=item['position'][1]-200
        for yy in range(y-2,y+3):
            for xx in range(x-2,x+3):
                image.putpixel((xx,yy), tuple(item['rgb']))
    return image


class LayoutFingerprintIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp_path = Path(directory.name)

    def test_record_persists_canvas_palette_dpi_and_zoom_signature(self):
        cache = self.tmp_path/'fp.json'
        entry = record_layout('skribbl-fast', _meta(), (180,260,780,620), _palette(), path=cache)
        assert entry['client_size'] == [800,500]
        assert entry['dpi'] == 96
        assert len(entry['zoom_signature']) == 16
        assert entry['browser_zoom_hint'] > 0
        data=load_cache(cache)
        assert data['entries'][0]['canvas_rel'] == [80,60,680,420]
        assert len(data['entries'][0]['palette']) == 8


    def test_quick_restore_matches_same_layout_and_reanchors(self):
        cache=self.tmp_path/'fp.json'; palette_path=self.tmp_path/'calibration.json'
        record_layout('skribbl-fast', _meta(), (180,260,780,620), _palette(), path=cache)
        result=try_restore('skribbl-fast', _meta(), palette_path, screenshot=_screen(), path=cache)
        assert result.hit
        assert result.canvas_box == (180,260,780,620)
        assert result.matched_swatches >= 5
        saved=json.loads(palette_path.read_text())
        assert saved['version'] == 4
        assert len(saved['colors']) == 8


    def test_quick_restore_rejects_wrong_zoom_layout_swatches(self):
        cache=self.tmp_path/'fp.json'; palette_path=self.tmp_path/'calibration.json'
        record_layout('skribbl-fast', _meta(), (180,260,780,620), _palette(), path=cache)
        wrong=Image.new('RGB',(800,500),(255,255,255))
        result=try_restore('skribbl-fast', _meta(), palette_path, screenshot=wrong, path=cache)
        assert not result.hit
        assert not palette_path.exists()


    def test_zoom_signature_changes_with_reflow(self):
        a,_=zoom_signature((0,0,1000,700),(100,100,800,600),[(100+i*20,650) for i in range(8)])
        b,_=zoom_signature((0,0,1000,700),(130,120,850,620),[(120+i*24,650) for i in range(8)])
        assert a != b



if __name__ == "__main__":
    unittest.main()
