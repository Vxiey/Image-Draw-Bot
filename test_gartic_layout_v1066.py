import unittest
from PIL import Image
from Colors import validate_calibration
from GarticPhoneLayout import (PALETTE_COLUMNS, PALETTE_ROWS, PALETTE_COLOR_COUNT,
                               REFERENCE_CANVAS_ASPECT, assess_canvas_size)
from PaletteMaps import GARTIC_PHONE, detect_preset, sample_grid, detect_color_swatches
from Version import APP_VERSION, FILE_VERSION


class GarticLayout1066Tests(unittest.TestCase):
    def test_reference_palette_is_full_6_by_12_grid(self):
        self.assertEqual((PALETTE_COLUMNS, PALETTE_ROWS, PALETTE_COLOR_COUNT), (6, 12, 72))
        self.assertEqual(len(GARTIC_PHONE.colors), 72)
        self.assertEqual(len(set(GARTIC_PHONE.colors)), 72)

    def test_reference_canvas_aspect(self):
        self.assertAlmostEqual(REFERENCE_CANVAS_ASPECT, 982/549, places=6)
        good=assess_canvas_size(982,549)
        self.assertTrue(good['likely'])
        self.assertGreater(good['confidence'], .99)
        bad=assess_canvas_size(1000,1000)
        self.assertFalse(bad['likely'])

    def test_detect_full_reference_palette(self):
        cell=14; gap=2
        w=PALETTE_COLUMNS*cell+(PALETTE_COLUMNS-1)*gap
        h=PALETTE_ROWS*cell+(PALETTE_ROWS-1)*gap
        im=Image.new('RGB',(w,h),(9,9,9))
        points=[]
        pix=im.load()
        for i,rgb in enumerate(GARTIC_PHONE.colors):
            row,col=divmod(i,PALETTE_COLUMNS)
            x0=col*(cell+gap);y0=row*(cell+gap)
            for y in range(y0,y0+cell):
                for x in range(x0,x0+cell): pix[x,y]=rgb
            points.append((x0+(cell-1)//2,y0+(cell-1)//2))
        got=detect_preset(im,GARTIC_PHONE)
        self.assertEqual(len(got),72)
        self.assertEqual(got,points)

    def test_grid_sampler_accepts_72_colors(self):
        im=Image.new('RGB',(6*10,12*10))
        pix=im.load()
        expected=[]
        for i,rgb in enumerate(GARTIC_PHONE.colors):
            row,col=divmod(i,6)
            for y in range(row*10,(row+1)*10):
                for x in range(col*10,(col+1)*10): pix[x,y]=rgb
            expected.append(rgb)
        _positions,rgbs=sample_grid(im,12,6)
        self.assertEqual(rgbs,list(expected))

    def test_calibration_schema_accepts_72_colors(self):
        data={'version':4,'colors':[
            {'name':f'C{i}','position':[i*2,100+i],'rgb':list(rgb)}
            for i,rgb in enumerate(GARTIC_PHONE.colors)
        ]}
        rows=validate_calibration(data)
        self.assertEqual(len(rows),72)

    def test_current_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')


if __name__=='__main__':
    unittest.main()
