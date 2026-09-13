import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from AdaptiveDetail import (ADAPTIVE_DETAIL_MODES, apply_adaptive_detail,
                            prune_flat_micro_strokes, resolve_adaptive_detail,
                            validate_adaptive_detail)


class AdaptiveDetailV1038Tests(unittest.TestCase):
    def noisy_scene(self):
        im=Image.new('RGB',(160,100),(230,230,230));pix=im.load()
        for y in range(im.height):
            for x in range(im.width):
                n=((x*17+y*31)%9)-4
                pix[x,y]=(230+n,230+n,230+n)
        d=ImageDraw.Draw(im)
        d.rectangle((45,20,115,80),fill=(60,100,180),outline=(10,10,10),width=2)
        d.ellipse((68,35,92,59),fill=(245,220,180),outline=(20,20,20),width=2)
        return im

    def test_modes_and_validation(self):
        self.assertEqual(ADAPTIVE_DETAIL_MODES,('Off','Auto','Preserve detail','Balanced','Strong simplify'))
        self.assertEqual(resolve_adaptive_detail('Auto',complexity_score=.5),'Preserve detail')
        self.assertEqual(resolve_adaptive_detail('Auto',complexity_score=.22),'Balanced')
        self.assertEqual(resolve_adaptive_detail('Auto',complexity_score=.05),'Strong simplify')
        self.assertEqual(resolve_adaptive_detail('Auto',complexity_score=.05,preview=True),'Balanced')
        with self.assertRaises(ValueError):validate_adaptive_detail('Destroy details')

    def test_flat_texture_is_simplified_but_hard_edge_is_preserved(self):
        im=self.noisy_scene()
        out,mask,stats=apply_adaptive_detail(im.convert('RGBA'),'Balanced')
        out=out.convert('RGB')
        self.assertEqual(out.getpixel((45,20)),im.getpixel((45,20)))
        self.assertNotEqual(out.getpixel((5,5)),im.getpixel((5,5)))
        self.assertGreater(stats.flat_pixels,stats.protected_pixels)
        self.assertGreater(mask.getpixel((45,20)),mask.getpixel((5,5)))

    def test_off_is_identity(self):
        im=self.noisy_scene().convert('RGBA')
        out,mask,stats=apply_adaptive_detail(im,'Off')
        self.assertEqual(out.tobytes(),im.tobytes())
        self.assertEqual(stats.effective_mode,'Off')
        self.assertEqual(mask.getextrema(),(255,255))

    def test_micro_pruning_only_removes_flat_short_runs(self):
        mask=Image.new('L',(20,10),0)
        # Protect the second tiny stroke and a long structural run.
        mask.putpixel((11,2),255)
        groups=[[(1,2,1,2),(10,2,11,2),(2,5,12,5)]]
        out,meta=prune_flat_micro_strokes(groups,mask,'Balanced')
        self.assertNotIn((1,2,1,2),out[0])
        self.assertIn((10,2,11,2),out[0])
        self.assertIn((2,5,12,5),out[0])
        self.assertEqual(meta['adaptive_detail_pruned_micro_strokes'],1)

    def test_subject_focus_increases_center_protection(self):
        im=Image.new('RGB',(100,100),(180,180,180))
        _,plain,_=apply_adaptive_detail(im,'Balanced',subject_focus=False)
        _,focus,_=apply_adaptive_detail(im,'Balanced',subject_focus=True)
        self.assertGreater(focus.getpixel((50,50)),plain.getpixel((50,50)))

    def test_profile_defaults_and_ui(self):
        from GameProfiles import profile_defaults
        self.assertEqual(profile_defaults('Microsoft Paint')['adaptive_detail'],'Auto')
        self.assertEqual(profile_defaults('Skribbl.io Fast')['adaptive_detail'],'Strong simplify')
        ui=Path('StudioUI.py').read_text(encoding='utf-8')
        bot=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("'Adaptive detail'",ui)
        self.assertIn('apply_adaptive_detail',bot)
        self.assertIn('adaptive_detail_meta',bot)


    def test_make_plan_reduces_low_contrast_texture_and_reports_meta(self):
        from DrawBot import make_plan
        im=Image.new('RGB',(120,80),(136,136,136));pix=im.load()
        for y in range(im.height):
            for x in range(im.width):
                v=132 if (x+y)%2==0 else 140
                pix[x,y]=(v,v,v)
        ImageDraw.Draw(im).rectangle((30,15,90,65),fill=(48,105,190),outline=(0,0,0),width=3)
        base=dict(detail=9,delay=.003,speed='Fast',precision='High',lines=True,drawing_mode='Smart paths (recommended)',
                  skip_white=False,contrast=1,outline=False,brush_px=2,max_seconds=180,paint_current_color=False,
                  background_fill='Off',background_simplification='Off',color_grouping='Accurate',color_workflow='Finish color first',
                  stroke_optimizer='Off',color_rendering='RGB nearest',color_layers='Off',custom_color_workflow='Calibrated palette',
                  cpu_workers='1',cpu_engine='Threads',ram_budget='512 MB',ram_custom_mb='512',planning_resolution='High',
                  gpu_mode='CPU',gpu_vram='Auto',gpu_performance='Balanced',progressive_rendering='Off',
                  time_budget_mode='Manual',target_stroke_count='Unlimited')
        off=make_plan(im.convert('RGBA'),(480,320),dict(base,adaptive_detail='Off'))
        adaptive=make_plan(im.convert('RGBA'),(480,320),dict(base,adaptive_detail='Strong simplify'))
        self.assertLess(adaptive['count'],off['count'])
        meta=adaptive['options']['adaptive_detail_meta']
        self.assertEqual(meta['adaptive_detail_effective'],'Strong simplify')
        self.assertGreater(meta['adaptive_detail_flat_pixels'],meta['adaptive_detail_protected_pixels'])

    def test_release_version(self):
        from Version import APP_VERSION,FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')


if __name__=='__main__':unittest.main()
