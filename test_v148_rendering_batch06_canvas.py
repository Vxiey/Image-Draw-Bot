"""The complete canvas guards a centered image; previews retain its image crop."""
from contextlib import ExitStack, closing
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from CanvasGuard import CanvasGuard, normalize_canvas_anchors
from EdgeBehavior import apply_edge_behavior
from Precision import CanvasTransform
from PreviewSafety import build_preview_safety_plan, draw_safe_paths, render_preview_safety_map


def close_plan(plan, original):
    for value in (*plan.values(), *plan.get('options', {}).values(), *plan.get('ui_previews', {}).values()):
        if isinstance(value, Image.Image) and value is not original:
            value.close()


class CanvasPlacementTests(unittest.TestCase):
    def test_both_letterbox_axes_and_negative_screen_origin_match_native_guard(self):
        for canvas, fitted, source_size in (((80,120),(80,40),(40,20)),
                                             ((120,80),(40,80),(20,40)),
                                             ((80,120),(31,20),(20,10))):
            for origin in ((101, 103), (-201, -151)):
                with self.subTest(canvas=canvas, fitted=fitted, origin=origin):
                    area = (*origin, *canvas)
                    polygon = ((0.,0.),(1.,0.),(1.,1.),(0.,1.))
                    anchors = ({'kind':'corner','center':(.2,.3),'tip':(.3,.4),'confidence':.95},)
                    options = {'brush_px':3,'edge_behavior':'Hard Clip',
                               '_planning_canvas_size':canvas,'_target_screen_area':area,
                               'canvas_polygon':polygon,'canvas_polygon_space':'normalized',
                               'canvas_anchors':anchors,'canvas_anchor_space':'normalized'}
                    w,h = source_size
                    entries = [{'color_index':0,'path':((2,0),(w-3,0)),'brush_px':1},
                               {'color_index':0,'path':((0,2),(0,h-3)),'brush_px':5},
                               {'color_index':0,'path':((w//2,h//2),)}]
                    result = build_preview_safety_plan(source_size,fitted,[[]],None,options,
                                                       execution_sequence=entries)
                    dx,dy = (canvas[0]-fitted[0])/2,(canvas[1]-fitted[1])/2
                    transform = CanvasTransform(w,h,fitted,origin[0]+dx,origin[1]+dy)
                    expected=[];brush=3
                    native_anchors=normalize_canvas_anchors(anchors,area=area,coordinate_space='normalized')
                    for entry in entries:
                        brush=entry.get('brush_px',brush)
                        native=CanvasGuard.from_area_or_polygon(area,polygon=polygon,coordinate_space='normalized',
                                                                brush_px=brush,edge_margin_px=2,anchors=native_anchors)
                        guarded=apply_edge_behavior(native,[transform.point(*p) for p in entry['path']],behavior='Hard Clip')
                        expected.extend({'color_index':0,'path':tuple((x-origin[0],y-origin[1]) for x,y in path),
                                         'brush_px':brush} for path in guarded.subpaths)
                    self.assertEqual(result.sequence,expected)
                    self.assertEqual(result.groups,[[row['path'] for row in expected]])
                    self.assertEqual(result.meta['image_offset'],(dx,dy))
                    self.assertEqual(result.meta['canvas_guard']['area'],(0,0,*canvas))
                    actual_anchor=result.meta['canvas_guard']['anchor_items'][0]
                    self.assertEqual(actual_anchor['center'],tuple(native_anchors[0].center[i]-origin[i] for i in (0,1)))

    def test_absolute_relative_and_normalized_evidence_share_whole_preview_canvas(self):
        area=(201,301,160,240);canvas=(80,120);fitted=(40,120)
        encodings=(('normalized',((0,0),(1,0),(1,1),(0,1)),(.2,.3)),
                   ('area',((0,0),(159,0),(159,239),(0,239)),(.2*159,.3*239)),
                   ('screen',((201,301),(360,301),(360,540),(201,540)),(201+.2*159,301+.3*239)))
        actual=[]
        for space,polygon,center in encodings:
            options={'brush_px':1,'edge_behavior':'Hard Clip','_planning_canvas_size':canvas,
                     '_target_screen_area':area,'canvas_polygon':polygon,'canvas_polygon_space':space,
                     'canvas_anchors':[{'kind':'corner','center':center,'confidence':.9}],
                     'canvas_anchor_space':space}
            result=build_preview_safety_plan((40,120),fitted,[[(0,60,39,60)]],None,options)
            guard=result.meta['canvas_guard'];actual.append((result.groups,guard['polygon'],guard['safe_polygon'],guard['anchor_items']))
            self.assertEqual(guard['polygon'],((0,0),(79,0),(79,119),(0,119)))
            self.assertAlmostEqual(guard['anchor_items'][0]['center'][0],.2*79)
            self.assertAlmostEqual(guard['anchor_items'][0]['center'][1],.3*119)
        self.assertEqual(actual[0],actual[1]);self.assertEqual(actual[0],actual[2])

    def test_actual_thin_source_plan_and_execution_keep_centered_canvas_strokes(self):
        from DrawBot import make_plan, execute_plan
        from test_pixel_accurate_v1086 import opts
        from test_drawbot import Mouse, NoWait
        for source_size, canvas in (((1,24),(200,48)),((24,1),(48,200))):
            with self.subTest(source=source_size), ExitStack() as stack:
                source=stack.enter_context(closing(Image.new('RGB',source_size,'black')))
                options=opts(preview_plan=True,unlimited_time=True,time_budget_mode='Unlimited',brush_px=1,
                             canvas_guard_brush_px=1,edge_behavior='Hard Clip',strict_color_verification=False,
                             adaptive_color_verification=False,visual_verification_enabled=False,
                             visual_verification_resolved='Off',detail_zoom='Off',corners=((100,100),(100+canvas[0],100+canvas[1])))
                stack.enter_context(patch('DrawBot.log_event'))
                stack.enter_context(patch('DrawBot.save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
                for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                             'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                             'CorrectionHistory.record_correction_history'):
                    stack.enter_context(patch(name,return_value={}))
                plan=make_plan(source,canvas,options)
                stack.callback(close_plan,plan,source)
                self.assertEqual(plan['options']['_planning_canvas_size'],canvas)
                self.assertGreater(plan['options']['preview_safety_meta']['drawable_subpaths'],0)
                self.assertFalse(plan['options']['preview_safety_meta']['stopped'])
                mouse=Mouse()
                execute_plan(plan,(100,100,*canvas),[(10+i*3,10) for i in range(len(plan['colors']))],mouse,
                             NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
                self.assertGreater(sum(action[0]=='press' for action in mouse.actions),0)
                self.assertEqual(plan['options']['runtime_path_counts']['sent'],plan['count'])
                self.assertEqual(plan['options']['runtime_safety_report']['counts']['skipped'],0)
                self.assertFalse(mouse.held)

    def test_image_preview_safety_stroke_and_debug_layers_subtract_letterbox_offset(self):
        from PreviewLayers import build_auxiliary_previews
        from SafetyDebugOverlay import render_safety_debug_overlay, ACTION_COLORS
        canvas=(120,100);fitted=(40,100);size=fitted
        options={'brush_px':1,'edge_behavior':'Hard Clip','_planning_canvas_size':canvas}
        groups=[[(0,80,39,80)]]
        result=build_preview_safety_plan(fitted,fitted,groups,None,options)
        self.assertEqual(result.groups,[[((40,80),(79,80))]])
        with ExitStack() as stack:
            source=stack.enter_context(closing(Image.new('RGB',fitted,'white')))
            preview=stack.enter_context(closing(Image.new('RGB',size,'white')))
            draw_safe_paths(ImageDraw.Draw(preview),result,fitted,size,[(0,0,0)],1)
            self.assertEqual({(x,y) for y in range(100) for x in range(40) if preview.getpixel((x,y))==(0,0,0)},
                             {(x,80) for x in range(40)})
            safety=stack.enter_context(closing(render_preview_safety_map(source,size,result,[(0,0,0)],1)))
            self.assertTrue(all(safety.getpixel((x,80))==(95,95,95) for x in range(40)))
            debug=stack.enter_context(closing(render_safety_debug_overlay(size,result,[(0,0,0)],1)))
            self.assertTrue(all(debug.getpixel((x,80))==ACTION_COLORS['drawn'] for x in range(40)))
            options.update(_preview_safety_groups=result.groups,preview_safety_meta=result.meta)
            layers=build_auxiliary_previews(source,size,groups,[(0,0,0)],lambda x,y:(x,y),1,options)
            for value in layers.values():stack.enter_context(closing(value))
            self.assertTrue(all(layers['stroke'].getpixel((x,80))!=(15,20,29) for x in range(40)))

    def test_subject_rectangle_stays_relative_to_fitted_source(self):
        from DrawBot import make_plan
        from test_pixel_accurate_v1086 import opts
        for source_size in ((80,40),(40,80)):
            with self.subTest(source_size=source_size), closing(Image.new('RGB',source_size,'black')) as source:
                with patch('DrawBot.log_event'):
                    plan=make_plan(source,(100,100),opts(subject_focus='Subject only',subject_region=(.2,.2,.8,.8),
                        preview_plan=True,unlimited_time=True,time_budget_mode='Unlimited',detail_zoom='Off'))
                try:
                    width,height=plan['image'].size
                    expected={(x,y) for y in range(int(height*.2),int(height*.8))
                              for x in range(int(width*.2),int(width*.8))}
                    painted={(x,y) for y in range(plan['preview'].height) for x in range(plan['preview'].width)
                             if plan['preview'].getpixel((x,y))==(0,0,0)}
                    self.assertEqual(painted,expected)
                    self.assertEqual(plan['options']['subject_region'],(.2,.2,.8,.8))
                finally:close_plan(plan,source)

    def test_actual_verified_brush_changes_use_the_same_whole_canvas_guard(self):
        from DrawBot import execute_plan
        from test_drawbot import Mouse, NoWait
        from test_visual_verification_v1043 import simple_visual_plan
        with ExitStack() as stack:
            plan=simple_visual_plan();plan['image'].close()
            plan['image']=stack.enter_context(closing(Image.new('RGB',(40,80),'white')))
            paths=[((0,20),(39,20)),((0,30),(39,30))]
            plan.update(fitted=(40,80),groups=[[(*p[0],*p[1]) for p in paths],[]],
                        execution_groups=[paths,[]],execution_sequence=[
                            {'color_index':0,'path':paths[0],'brush_px':5},
                            {'color_index':0,'path':paths[1],'brush_px':1}],count=2)
            plan['options'].update(brush_px=5,canvas_guard_brush_px=5,_planning_canvas_size=(120,80),
                                  corners=((100,100),(220,180)),unlimited_time=True,
                                  strict_color_verification=False,adaptive_color_verification=False,
                                  visual_verification_enabled=False,visual_verification_resolved='Off',
                                  browser_brush_plan={'target_position':(25,10),'target_index':1,'effective_px':5,
                                      'control_positions':[(15,10),(25,10)],'nominal_sizes':[1,5],
                                      'verified_sizes':[1,5],'confidence':.95,'safe_guard_px':5})
            preview=build_preview_safety_plan((40,80),(40,80),plan['groups'],plan['execution_groups'],
                                             plan['options'],execution_sequence=plan['execution_sequence'])
            self.assertEqual(preview.meta['safety_debug']['drawn'],2)
            self.assertEqual(set(preview.meta['canvas_guards_by_brush']),{'1','5'})
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
            stack.enter_context(patch('BrowserBrushSize.verify_brush_selection',return_value=True))
            for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name,return_value={}))
            mouse=Mouse()
            execute_plan(plan,(100,100,120,80),[(10,10),(20,10)],mouse,NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
            self.assertEqual(plan['options']['runtime_safety_report']['counts']['drawn'],2)
            self.assertEqual(sum(a[0]=='press' for a in mouse.actions),2)
            self.assertGreaterEqual(plan['options']['adaptive_brush_runtime_meta']['switches'],1)
            self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'],1)


if __name__=='__main__':unittest.main()
